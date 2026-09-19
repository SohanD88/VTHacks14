"""Fast contracts use a tiny decoded video and a controlled reconstruction provider.
The separate evaluate_videos.py command runs the actual models on real footage.
"""

import time
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.video import ProcessingError, discover_videos, extract, metadata


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "input.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 64))
    rng = np.random.default_rng(5)
    base = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8)
    for i in range(15):
        writer.write(np.roll(base, i, axis=1))
    writer.release()
    return path.read_bytes()


class Provider:
    def reconstruct(self, path, scan, output, update, check):
        cap = cv2.VideoCapture(str(path))
        count = 0
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            count += 1
            check()
            update(frames=count, progress=count)
        cap.release()
        geometry = Geometry(
            vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            colors=[(1, 0, 0)] * 3,
            triangles=[(0, 1, 2)],
        )
        objs = [
            SceneObject(
                id="chair",
                kind="chair",
                label="Chair",
                position=(0, 0.5, 0),
                size=(1, 1, 1),
                confidence=0.8,
                original_transform=Transform(position=(0, 0.5, 0)),
                geometry=geometry,
            ),
            SceneObject(
                id="door",
                kind="door",
                label="Opening candidate",
                position=(2, 1, 0),
                size=(1, 2, 0.1),
                confidence=0.7,
                structural=True,
                movable=False,
                entrance=True,
                original_transform=Transform(position=(2, 1, 0)),
                geometry=geometry,
            ),
        ]
        scan.scene = Scene(objects=objs)
        scan.status = "degraded"
        scan.progress = 100
        scan.stats.objects = 2
        scan.stats.entrances = 1
        (output / "cloud.ply").write_text("ply\n")
        return scan


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", max_stored_scans=8))
    app.state.reconstruction = Provider()
    with TestClient(app) as client:
        yield client


def submit(client, video, **data):
    return client.post(
        "/api/scans",
        files={"file": ("../../unsafe.avi", video, "video/avi")},
        data={"name": "Room", "mode": "quick", **data},
    )


def finish(client, id):
    for _ in range(200):
        scan = client.get(f"/api/scans/{id}").json()
        if scan["status"] in {"completed", "degraded", "failed", "cancelled"}:
            return scan
        time.sleep(0.01)
    pytest.fail("Job did not finish")


def test_upload_progress_result_artifact_and_health(client, video):
    assert client.get("/api/health").json()["processing_mode"] == "video-reconstruction"
    response = submit(client, video)
    assert response.status_code == 202
    id = response.json()["id"]
    scan = finish(client, id)
    assert scan["stats"]["frames"] == 15
    assert scan["scene"]["objects"][1]["entrance"]
    assert scan["video"]["filename"] == "unsafe.avi"
    assert client.get(f"/api/scans/{id}/status").json()["progress"] == 100
    assert "scene" not in client.get(f"/api/scans/{id}/status").json()
    assert client.get(f"/api/scans/{id}/artifacts/cloud.ply").status_code == 200
    assert client.get(f"/api/scans/{id}/artifacts/job.json").status_code == 404
    assert client.get("/api/scans").json()[0]["id"] == id


@pytest.mark.parametrize(
    "filename,content,expected",
    [("bad.txt", b"x", 415), ("empty.mp4", b"", 422), ("corrupt.mov", b"not a video", 422)],
)
def test_upload_validation(client, filename, content, expected):
    response = client.post("/api/scans", files={"file": (filename, content)})
    assert response.status_code == expected
    assert "Traceback" not in response.text


def test_limits_and_missing(client, video):
    client.app.state.settings.max_upload_bytes = 10
    assert submit(client, video).status_code == 413
    assert client.get(f"/api/scans/{uuid4()}").status_code == 404
    assert client.get("/api/scans/invalid-id").status_code == 422
    client.app.state.scan_store.capacity = 1
    assert submit(client, video).status_code == 429


def test_edit_persistence_export_import_reset_protection(client, video):
    id = submit(client, video).json()["id"]
    scan = finish(client, id)
    scene = scan["scene"]
    scene["objects"][0]["position"][0] = 1

    def save(scene, revision, **extra):
        return client.put(
            f"/api/scans/{id}/scene", json={"scene": scene, "revision": revision, **extra}
        )

    result = save(scene, 0)
    assert result.status_code == 200
    assert result.json()["scene"]["objects"][0]["modified"]
    assert save(scene, 0).status_code == 409
    scene["objects"][1]["deleted"] = True
    assert save(scene, 1).status_code == 422
    assert save(scene, 1, structural_editing=True).status_code == 422
    assert (
        save(scene, 1, structural_editing=True, confirm_structural_deletion=True).status_code == 200
    )
    bundle = client.get(f"/api/scans/{id}/export").json()
    assert bundle["scan"]["scene"]["objects"][0]["position"][0] == 1
    imported = client.post("/api/scans/import", json=bundle)
    assert imported.status_code == 201
    assert imported.json()["scene"] == bundle["scan"]["scene"]
    restored = client.post(f"/api/scans/{id}/reset").json()
    assert restored["scene"] == bundle["original"]
    assert client.get(f"/api/scans/{id}/original").json() == bundle["original"]
    assert client.delete(f"/api/scans/{id}").status_code == 200
    assert client.get(f"/api/scans/{id}").status_code == 404


def test_invalid_scene_edit_and_import(client, video):
    id = submit(client, video).json()["id"]
    scan = finish(client, id)
    scene = scan["scene"]
    scene["objects"][0]["geometry"]["triangles"] = [[0, 1, 999]]
    assert (
        client.put(f"/api/scans/{id}/scene", json={"scene": scene, "revision": 0}).status_code
        == 422
    )
    assert client.post("/api/scans/import", json={"bad": 1}).status_code == 422
    assert client.post("/api/scans/import", content=b"not json").status_code == 422


def test_cancellation_and_safe_failure(client, video):
    class Slow:
        def reconstruct(self, path, scan, output, update, check):
            for _ in range(1000):
                check()
                time.sleep(0.002)

    client.app.state.reconstruction = Slow()
    id = submit(client, video).json()["id"]
    assert client.get("/api/health").status_code == 200
    assert client.post(f"/api/scans/{id}/cancel").status_code == 200
    assert finish(client, id)["status"] == "cancelled"

    class Broken:
        def reconstruct(self, *args):
            raise ValueError("/private/secret stack detail")

    client.app.state.reconstruction = Broken()
    id = submit(client, video).json()["id"]
    result = finish(client, id)
    assert result["status"] == "failed"
    assert "/private" not in str(result)
    assert result["error"]


def test_restart_recovers_scene_and_marks_interrupted(tmp_path, video):
    config = Settings(data_dir=tmp_path / "persist")
    app = create_app(config)
    app.state.reconstruction = Provider()
    with TestClient(app) as first:
        id = submit(first, video).json()["id"]
        scan = finish(first, id)
        interrupted = app.state.scan_store.reserve()
        interrupted_id = str(interrupted.id)
    with TestClient(create_app(config)) as second:
        assert second.get(f"/api/scans/{id}").json()["scene"] == scan["scene"]
        result = second.get(f"/api/scans/{interrupted_id}").json()
        assert result["status"] == "failed"
        assert "restarted" in result["error"]


def test_decode_and_quality_are_content_based(tmp_path, video):
    path = tmp_path / "tests" / "nested" / "renamed.avi"
    path.parent.mkdir(parents=True)
    path.write_bytes(video)
    assert discover_videos(tmp_path / "tests") == [path]
    info = metadata(path, "renamed.avi")
    assert info.total_frames == 15
    frames, report, decoded = extract(path, info, tmp_path, "quick", lambda **_: None, lambda: None)
    assert decoded == 15
    assert 2 <= len(frames) <= 12
    assert sum(r["reason"] == "accepted" for r in report) == len(frames)
    bad = tmp_path / "bad.avi"
    bad.write_bytes(b"garbage")
    with pytest.raises(ProcessingError):
        metadata(bad, "bad.avi")


def test_cors(client):
    response = client.options(
        "/api/scans",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200


def test_sparse_transform_transaction(client, video):
    id = submit(client, video).json()["id"]
    finish(client, id)
    change = {"id": "chair", "position": [1, 0.5, 0], "rotation": [0, 0.2, 0], "scale": [1, 1, 1]}
    response = client.patch(
        f"/api/scans/{id}/transforms", json={"revision": 0, "changes": [change]}
    )
    assert response.status_code == 200
    assert "scene" not in response.json()
    assert client.get(f"/api/scans/{id}").json()["scene"]["objects"][0]["position"][0] == 1
    assert (
        client.patch(
            f"/api/scans/{id}/transforms", json={"revision": 0, "changes": [change]}
        ).status_code
        == 409
    )
    change["id"] = "door"
    assert (
        client.patch(
            f"/api/scans/{id}/transforms", json={"revision": 1, "changes": [change]}
        ).status_code
        == 422
    )


def test_storage_reservation_budget(client, video):
    client.app.state.scan_store.max_bytes = 1024
    response = submit(client, video)
    assert response.status_code == 429
    assert "storage limit" in response.json()["error"]["message"]


def test_import_cannot_replace_original_geometry(client, video):
    id = submit(client, video).json()["id"]
    finish(client, id)
    bundle = client.get(f"/api/scans/{id}/export").json()
    bundle["scan"]["scene"]["objects"][0]["geometry"]["vertices"][0][0] = 99
    assert client.post("/api/scans/import", json=bundle).status_code == 422


def test_furniture_meshes_have_multiple_parts_and_grounded_bounds():
    from app.services.assets import furniture

    for kind in ["chair", "sofa", "table"]:
        mesh = furniture(kind, [1, 1, 1], [0.5, 0.5, 0.5])
        vertices = np.asarray(mesh.vertices)
        assert len(mesh.vertices) > 8  # A single bounding cuboid is insufficient.
        assert len(mesh.triangles) > 12
        assert np.isfinite(vertices).all()
        assert vertices[:, 1].min() >= -0.501
        assert vertices[:, 1].max() <= 0.501


def test_floor_refinement_preserves_observed_footprint_and_other_elevations():
    from app.services.geometry import stabilize_floor

    points = np.array([[1.0, 0.1, 2.0], [2.0, -0.2, 3.0], [4.0, 0.7, 5.0]])
    refined = stabilize_floor(points)
    np.testing.assert_array_equal(refined[:, [0, 2]], points[:, [0, 2]])
    np.testing.assert_array_equal(refined[:, 1], [0, 0, 0.7])
    assert points[0, 1] == 0.1


def test_calibration_roundtrip_history_and_structural_protection(client, video):
    from copy import deepcopy

    scan = finish(client, submit(client, video).json()["id"])
    id = scan["id"]
    original = deepcopy(scan["scene"])
    reference = {
        "reference_points": [[0, 0, 0], [0.5334, 0, 0]],
        "distance_m": 1.0668,
        "basis": "assumed",
    }
    response = client.post(
        f"/api/scans/{id}/calibration", json={"revision": 0, "calibration": reference}
    )
    assert response.status_code == 200, response.text
    scaled = response.json()["scene"]
    for actual, before in zip(scaled["objects"], original["objects"]):
        assert actual["position"] == [2 * x for x in before["position"]]
        assert actual["scale"] == [2, 2, 2]
        assert actual["geometry"] == before["geometry"]
        assert actual["original_transform"] == before["original_transform"]
        assert not actual["modified"]
    assert "user-assumed 1.0668 m" in scaled["scale_note"]
    assert client.get(f"/api/scans/{id}/original").json() == original
    assert (
        client.post(
            f"/api/scans/{id}/calibration", json={"revision": 0, "calibration": reference}
        ).status_code
        == 409
    )
    # Reapplying the same reference is idempotent, not another 2x multiplication.
    again = client.post(
        f"/api/scans/{id}/calibration", json={"revision": 1, "calibration": reference}
    ).json()
    assert again["scene"] == scaled
    door = dict(scaled["objects"][1])
    door_change = {k: door[k] for k in ("id", "position", "rotation", "scale", "deleted")}
    door_change["position"][0] += 1
    assert (
        client.patch(
            f"/api/scans/{id}/transforms", json={"revision": 2, "changes": [door_change]}
        ).status_code
        == 422
    )
    # Ordinary furniture edits work while the scale is calibrated.
    change = {"id": "chair", "position": [1, 1, 0], "rotation": [0, 0.3, 0], "scale": [2, 2, 2]}
    assert (
        client.patch(
            f"/api/scans/{id}/transforms", json={"revision": 2, "changes": [change]}
        ).status_code
        == 200
    )
    bundle = client.get(f"/api/scans/{id}/export").json()
    imported = client.post("/api/scans/import", json=bundle)
    assert imported.status_code == 201, imported.text
    assert imported.json()["scene"] == bundle["scan"]["scene"]
    assert imported.json()["scene"]["objects"][0]["modified"]
    # Undo calibration and furniture editing in one revision, without structural unlock.
    changes = [
        {k: obj[k] for k in ("id", "position", "rotation", "scale", "deleted")}
        for obj in original["objects"]
    ]
    undo = client.patch(
        f"/api/scans/{id}/transforms", json={"revision": 3, "calibration": None, "changes": changes}
    )
    assert undo.status_code == 200, undo.text
    assert client.get(f"/api/scans/{id}").json()["scene"] == original
    # Full-scene saves cannot rewrite the calibrated camera path or semantic evidence.
    tampered = deepcopy(scaled)
    tampered["camera_path"] = [[9, 9, 9]]
    assert (
        client.put(f"/api/scans/{id}/scene", json={"revision": 4, "scene": tampered}).status_code
        == 422
    )
    assert client.post(f"/api/scans/{imported.json()['id']}/reset").json()["scene"] == original


@pytest.mark.parametrize(
    "points,distance",
    [([[0, 0, 0], [0, 0, 0]], 1), ([[0, 0, 0], [1, 0, 0]], 0), ([[0, 0, 0], [0.01, 0, 0]], 100)],
)
def test_calibration_rejects_invalid_reference_without_mutation(client, video, points, distance):
    scan = finish(client, submit(client, video).json()["id"])
    id = scan["id"]
    response = client.post(
        f"/api/scans/{id}/calibration",
        json={"revision": 0, "calibration": {"reference_points": points, "distance_m": distance}},
    )
    assert response.status_code == 422
    assert client.get(f"/api/scans/{id}").json() == scan
