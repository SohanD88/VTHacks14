"""Prepared artifacts retain geometry and load without a reconstruction provider."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Scene
from app.services import prepared_demo


def test_prepared_demo_loads_reuses_and_resets(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "scans"))

    def unexpected(*args, **kwargs):
        raise AssertionError("Prepared demo must not run Blender or reconstruction")

    app.state.blender.reconstruct = unexpected
    app.state.reconstruction.reconstruct = unexpected
    with TestClient(app) as client:
        response = client.post("/api/scans/demo")
        assert response.status_code == 200, response.text
        scan = response.json()
        scene = Scene.model_validate(scan["scene"])
        assert scan["source"] == "import" and scan["progress"] == 100
        assert scene.asset and len(scene.objects) > 80
        assert len([o for o in scene.objects if o.entrance]) == 3
        cross = next(o for o in scene.objects if "cross-passage" in o.label and o.kind == "floor")
        assert cross.position[0] == 0 and cross.size[0] > 3
        # The atrium opening must not become an invented solid floor.
        for obj in scene.objects:
            if obj.kind != "floor":
                continue
            assert not (
                abs(obj.position[0]) < obj.size[0] / 2
                and abs(-5 - obj.position[2]) < obj.size[2] / 2
            )
        assert any(o.kind == "ceiling" and o.cutaway_hidden for o in scene.objects)
        assert any(o.kind == "sofa" for o in scene.objects)
        entrance = next(o for o in scene.objects if o.label == "Entrance glazed door")
        assert entrance.position[0] < -4.0  # Relocated to the corridor left wall.
        doors = {o.label: o.id for o in scene.objects if o.entrance}
        route = client.post(
            f"/api/scans/{scan['id']}/routes",
            json={
                "revision": 0,
                "start": {"object_id": doors["Entrance glazed door"]},
                "end": {"object_id": doors["Final exit double doors"]},
            },
        )
        assert route.status_code == 200, route.text
        # The near-entry cross-passage is a usable shortcut; the planner need not
        # walk to the far lounge or cross the empty opening.
        assert min(point[2] for point in route.json()["polyline"]) > -2.05
        again = client.post("/api/scans/demo").json()
        assert again["id"] == scan["id"]
        assert client.get(f"/api/scans/{scan['id']}/artifacts/model.glb").content[:4] == b"glTF"
        assert (
            client.get(f"/api/scans/{scan['id']}/original").json()["asset"]["sha256"]
            == scene.asset.sha256
        )
        assert client.post(f"/api/scans/{scan['id']}/reset").status_code == 200


def test_missing_demo_is_actionable_and_does_not_reserve_a_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(prepared_demo, "DEMO_DIR", tmp_path / "missing")
    with TestClient(create_app(Settings(data_dir=tmp_path / "scans"))) as client:
        response = client.post("/api/scans/demo")
        assert response.status_code == 409
        assert "not been built" in response.text
        assert client.get("/api/scans").json() == []


def test_video_fingerprint_uses_contents_not_filename(tmp_path, monkeypatch):
    import hashlib
    import json

    monkeypatch.setattr(prepared_demo, "DEMO_DIR", tmp_path)
    known = hashlib.sha256(b"known reference").hexdigest()
    (tmp_path / "source.json").write_text(json.dumps({"sha256": known}))
    assert prepared_demo.matches_demo(known)
    assert not prepared_demo.matches_demo(hashlib.sha256(b"different video").hexdigest())


def test_prepared_video_stages_are_paced_and_cancellable(tmp_path, monkeypatch):
    from uuid import uuid4

    import pytest

    from app.schemas import ScanResponse
    from app.services.video import Cancelled

    scan = ScanResponse(id=uuid4(), name="Reference upload", source="video")
    steps = []
    deadlines = []
    service = prepared_demo.PreparedVideoService()
    monkeypatch.setattr(prepared_demo.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        service, "wait_until", lambda deadline, check: (deadlines.append(deadline), check())
    )
    service.reconstruct(
        tmp_path / "input.mov", scan, tmp_path, lambda **p: steps.append(p), lambda: None
    )
    assert deadlines == [102, 104, 106, 108, 110]
    assert [s["progress"] for s in steps] == [10, 30, 55, 75, 90, 100]
    assert all("demo" in s["message"].lower() for s in steps)
    assert scan.source == "video" and scan.scene.asset

    def cancel():
        raise Cancelled()

    with pytest.raises(Cancelled):
        service.reconstruct(tmp_path / "input.mov", scan, tmp_path, lambda **p: None, cancel)


def test_matching_video_upload_queues_prepared_provider_without_blender(tmp_path, monkeypatch):
    import hashlib
    import json

    from app.routes import scans
    from app.schemas import VideoMetadata

    reference = tmp_path / "reference"
    reference.mkdir()
    content = b"exact-demo-reference-bytes"
    (reference / "source.json").write_text(
        json.dumps({"sha256": hashlib.sha256(content).hexdigest()})
    )
    monkeypatch.setattr(prepared_demo, "DEMO_DIR", reference)
    monkeypatch.setattr(
        scans,
        "metadata",
        lambda *args: VideoMetadata(
            filename="renamed.mov",
            format="mov",
            codec="hevc",
            width=1920,
            height=1080,
            fps=30,
            duration=50,
            total_frames=1500,
        ),
    )
    app = create_app(Settings(data_dir=tmp_path / "scans"))
    calls = []
    app.state.scan_store.submit = lambda scan, path, provider: calls.append(provider)

    def unavailable():
        from app.services.video import ProcessingError

        raise ProcessingError("Blender unavailable")

    app.state.blender.executable = unavailable
    with TestClient(app) as client:
        response = client.post(
            "/api/scans",
            data={"name": "Demo", "mode": "blender"},
            files={"file": ("renamed.mov", content, "video/quicktime")},
        )
        assert response.status_code == 202, response.text
        assert isinstance(calls[0], prepared_demo.PreparedVideoService)
        assert response.json()["stage"] == "demo_queued"
        response = client.post(
            "/api/scans",
            data={"name": "Other", "mode": "blender"},
            files={"file": ("IMG_1343 2.MOV", b"not the reference", "video/quicktime")},
        )
        assert response.status_code == 503
        assert len(calls) == 1
