"""Contracts around imported assets, controlled generation and worker cancellation."""

import base64
import hashlib
import json
import struct
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas import Geometry, ModelAsset, Scene, SceneObject, Transform
from app.services.blender import run_process
from app.services.calibration import validate_edit
from app.services.room_plan import RoomPlan, plan_video
from app.services.video import ProcessingError


def asset_for(doc):
    encoded = json.dumps(doc).encode()
    encoded += b" " * (-len(encoded) % 4)
    raw = struct.pack("<4sIIII", b"glTF", 2, 20 + len(encoded), len(encoded), 0x4E4F534A) + encoded
    return dict(data=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())


def sample_scene():
    asset = ModelAsset(
        **asset_for({"asset": {"version": "2.0"}, "nodes": [{"extras": {"spatial_id": "chair"}}]})
    )
    return Scene(
        asset=asset,
        objects=[
            SceneObject(
                id="chair",
                asset_node="chair",
                label="Chair",
                kind="chair",
                confidence=0.8,
                position=(1, 0.5, 0),
                size=(1, 1, 1),
                original_transform=Transform(position=(1, 0.5, 0)),
                geometry=Geometry(
                    vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                    triangles=[(0, 1, 2)],
                    colors=[(0.5, 0.5, 0.5)] * 3,
                ),
                provenance="blender_generated",
                cutaway_hidden=False,
            )
        ],
    )


def test_glb_integrity_external_resources_and_node_mapping():
    scene = sample_scene()
    assert Scene.model_validate_json(scene.model_dump_json()) == scene
    with pytest.raises(ValidationError, match="checksum"):
        ModelAsset(data=scene.asset.data, sha256="0" * 64)
    for external in ["buffers", "images"]:
        with pytest.raises(ValidationError, match="embed"):
            ModelAsset(
                **asset_for({"asset": {"version": "2.0"}, external: [{"uri": "remote.png"}]})
            )
    with pytest.raises(ValidationError, match="Invalid GLB"):
        ModelAsset(**asset_for([]))
    data = scene.model_dump()
    data["objects"][0]["asset_node"] = "missing"
    with pytest.raises(ValidationError, match="must match"):
        Scene.model_validate(data)


def test_asset_and_geometry_are_immutable_but_transforms_are_editable():
    original = sample_scene()
    edited = original.model_copy(deep=True)
    edited.objects[0].position = (2, 0.5, 0)
    validate_edit(original, edited)
    edited.objects[0].cutaway_hidden = True
    with pytest.raises(ValueError):
        validate_edit(original, edited)
    edited = original.model_copy(deep=True)
    edited.asset = ModelAsset(
        **asset_for(
            {
                "asset": {"version": "2.0"},
                "nodes": [{"extras": {"spatial_id": "chair"}, "name": "modified"}],
            }
        )
    )
    with pytest.raises(ValueError):
        validate_edit(original, edited)


@pytest.fixture
def plan():
    return dict(
        width=5,
        depth=6,
        height=2.8,
        walls=["front", "back", "left", "right"],
        ceiling=True,
        doors=[dict(wall="front", offset=0, width=1.0668, height=2.1, source_frames=[1])],
        furniture=[
            dict(
                label="Couch",
                kind="sofa",
                x=0,
                y=0,
                width=2,
                depth=1,
                height=0.9,
                rotation_degrees=0,
                source_frames=[1],
            )
        ],
        assumptions=["Approximate dimensions from video."],
    )


def test_plan_rejects_impossible_geometry_and_executable_fields(plan):
    assert RoomPlan.model_validate(plan).doors[0].width == 1.0668
    for mutate in [
        lambda p: p["doors"][0].update(offset=10),
        lambda p: p["doors"].append(dict(p["doors"][0])),
        lambda p: p["furniture"][0].update(x=3),
        lambda p: p["furniture"][0].update(height=4),
        lambda p: p.update(python="import os"),
    ]:
        changed = json.loads(json.dumps(plan))
        mutate(changed)
        with pytest.raises(ValidationError):
            RoomPlan.model_validate(changed)


def test_video_requires_explicit_vision_configuration(tmp_path):
    with pytest.raises(ProcessingError, match="not configured"):
        plan_video(
            tmp_path / "missing.mp4",
            None,
            tmp_path,
            Settings(blender_api_key="", blender_planner_model=""),
            lambda **kw: None,
            lambda: None,
        )


def test_planner_uses_images_and_validates_frame_evidence(tmp_path, monkeypatch, plan):
    import app.services.room_plan as planner

    monkeypatch.setattr(planner, "extract", lambda *args: ([(1, None)], {}, 1))
    (tmp_path / "frame-000001.jpg").write_bytes(b"image fixture")
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200, json={"output": [{"content": [{"type": "output_text", "text": json.dumps(plan)}]}]}
        )

    client_class = httpx.Client
    monkeypatch.setattr(
        planner.httpx,
        "Client",
        lambda **kw: client_class(transport=httpx.MockTransport(respond), **kw),
    )
    settings = Settings(blender_api_key="test", blender_planner_model="vision-test")
    args = (
        tmp_path / "clip.mp4",
        SimpleNamespace(video=None),
        tmp_path,
        settings,
        lambda **kw: None,
        lambda: None,
    )
    assert plan_video(*args).furniture[0].kind == "sofa"
    assert calls[0]["store"] is False
    assert calls[0]["text"]["format"]["strict"] is True
    assert calls[0]["input"][0]["content"][-1]["type"] == "input_image"
    plan["doors"][0]["source_frames"] = [999]
    with pytest.raises(ProcessingError, match="failed validation"):
        plan_video(*args)


def test_worker_cancellation_and_timeout_stop_process(tmp_path):
    def cancel():
        raise ProcessingError("Cancelled by test")

    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    start = time.monotonic()
    with pytest.raises(ProcessingError, match="Cancelled"):
        run_process(command, tmp_path / "cancel.log", 30, cancel)
    with pytest.raises(ProcessingError, match="timed out"):
        run_process(command, tmp_path / "timeout.log", 0.05, lambda: None)
    assert time.monotonic() - start < 5


def test_model_upload_routes_to_blender_and_portable_export_roundtrip(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", max_stored_scans=4))

    class ModelProvider:
        def executable(self):
            return sys.executable

        def reconstruct(self, path, scan, output, update, check):
            assert path.suffix == ".blend"
            scan.scene = sample_scene()
            scan.status = "degraded"
            return scan

    app.state.blender = ModelProvider()
    with TestClient(app) as client:
        r = client.post("/api/scans", files={"file": ("test.blend", b"test-fixture")})
        assert r.status_code == 202, r.text
        sid = r.json()["id"]
        for _ in range(100):
            scan = client.get("/api/scans/" + sid).json()
            if scan["status"] not in {"queued", "processing"}:
                break
            time.sleep(0.01)
        assert scan["status"] == "degraded", scan
        assert scan["processing_mode"] == "blender"
        assert scan["source"] == "import" and scan["video"] is None
        exported = client.get(f"/api/scans/{sid}/export").json()
        response = client.post("/api/scans/import", json=exported)
        assert response.status_code == 201, response.text
        assert response.json()["scene"]["asset"] == scan["scene"]["asset"]
        assert response.json()["scene"]["objects"] == scan["scene"]["objects"]


@pytest.mark.parametrize(
    "nodes", [None, [1], [{"extras": "invalid"}], [{"children": [0]}], [{"children": [999]}]]
)
def test_malformed_glb_graphs_rejected(nodes):
    with pytest.raises(ValidationError):
        ModelAsset(**asset_for({"asset": {"version": "2.0"}, "nodes": nodes}))


def test_preview_direction_survives_export_and_cannot_be_zero():
    scene = sample_scene()
    scene.preview_direction = (0, 0.4, -1)
    assert Scene.model_validate_json(scene.model_dump_json()).preview_direction == (0, 0.4, -1)
    data = scene.model_dump()
    data["preview_direction"] = [0, 0, 0]
    with pytest.raises(ValidationError, match="nonzero"):
        Scene.model_validate(data)


@pytest.mark.parametrize("always_fail", [False, True])
def test_gemini_compatibility_repair_is_bounded(tmp_path, monkeypatch, always_fail):
    from uuid import uuid4

    from app.schemas import ScanResponse
    from app.services import gemini
    from app.services.blender import BlenderService

    service = BlenderService(Settings(_env_file=None, blender_provider="gemini"))
    monkeypatch.setattr(service, "executable", lambda: sys.executable)
    generations, builds = [], []
    source = tmp_path / "gemini-scene.py"

    def generate(*args, **kwargs):
        generations.append(kwargs)
        source.write_text("import bpy\n")
        return source

    def execute(*args):
        builds.append(True)
        if len(builds) == 1 or always_fail:
            raise ProcessingError("Blender compatibility failure")
        scene = sample_scene()
        (tmp_path / "model.glb").write_bytes(base64.b64decode(scene.asset.data))
        (tmp_path / "blender-scene.json").write_text(
            json.dumps(
                {
                    "objects": [o.model_dump() for o in scene.objects],
                    "scale_note": "Estimated",
                    "unobserved": "Unknown",
                    "warnings": [],
                }
            )
        )

    monkeypatch.setattr(gemini, "generate", generate)
    monkeypatch.setattr(service, "execute", execute)
    scan = ScanResponse(id=uuid4(), name="Gemini repair test")
    args = (tmp_path / "input.mov", scan, tmp_path, lambda **kw: None, lambda: None)
    if always_fail:
        with pytest.raises(ProcessingError, match="compatibility"):
            service.reconstruct(*args)
    else:
        assert service.reconstruct(*args).scene.asset is not None
    assert len(generations) == len(builds) == 2
    assert generations[1]["previous"] == "import bpy\n"
    assert "compatibility" in generations[1]["failure"]
