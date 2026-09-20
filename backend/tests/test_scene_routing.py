"""Routing must respect edited rendered geometry, revisions, and missing floor data."""

from math import pi
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routing.scene_adapter import AdapterError, SceneRouteRequest, route_scene, world_vertices
from app.schemas import Geometry, ScanResponse, Scene, SceneObject, Transform


def box(id, kind, position, size):
    vertices = [
        (x * size[0], y * size[1], z * size[2])
        for x in (-0.5, 0.5)
        for y in (-0.5, 0.5)
        for z in (-0.5, 0.5)
    ]
    return SceneObject(
        id=id,
        label=id,
        kind=kind,
        confidence=0.9,
        position=position,
        size=size,
        original_transform=Transform(position=position),
        entrance=kind == "door",
        geometry=Geometry(
            vertices=vertices,
            colors=[(0.5, 0.5, 0.5)] * 8,
            triangles=[
                (0, 1, 3),
                (0, 3, 2),
                (4, 6, 7),
                (4, 7, 5),
                (0, 4, 5),
                (0, 5, 1),
                (2, 3, 7),
                (2, 7, 6),
                (0, 2, 6),
                (0, 6, 4),
                (1, 5, 7),
                (1, 7, 3),
            ],
        ),
    )


def room(*objects):
    return Scene(objects=[box("floor", "floor", (0, -0.05, 0), (6, 0.1, 6)), *objects])


def request(**overrides):
    return SceneRouteRequest.model_validate(
        {
            "revision": 0,
            "start": {"point": [-2, 0, 0]},
            "end": {"point": [2, 0, 0]},
            **overrides,
        }
    )


def test_route_uses_engine_and_goes_around_furniture_without_mutating_scene(monkeypatch):
    import app.routing.scene_adapter as adapter

    calls = []
    actual = adapter.plan

    def track(graph, mission, **options):
        calls.append(graph)
        return actual(graph, mission, **options)

    monkeypatch.setattr(adapter, "plan", track)
    scene = room(box("table", "table", (0, 0.5, 0), (1, 1, 1.5)))
    before = scene.model_dump_json()
    result = route_scene(scene, request(), "scan")
    assert len(calls) == 1
    assert result["estimated"] is True and result["distance_m"] > 4.1
    assert max(abs(p[2]) for p in result["polyline"]) > 0.95
    assert scene.model_dump_json() == before
    # Sample every displayed segment: it cannot cut back through the inflated table.
    for a, b in zip(result["polyline"], result["polyline"][1:]):
        for t in np.linspace(0, 1, 80):
            p = np.array(a) * (1 - t) + np.array(b) * t
            assert abs(p[0]) >= 0.7 or abs(p[2]) >= 0.95


def test_solid_wall_blocks_route_even_when_hidden_or_low_confidence():
    wall = box("wall", "wall", (0, 1, 0), (0.1, 2, 6))
    wall.cutaway_hidden = True
    wall.confidence = 0.1
    with pytest.raises(AdapterError, match="No path connects"):
        route_scene(room(wall), request(), "scan")
    wall.deleted = True
    assert route_scene(room(wall), request(), "scan")["distance_m"] < 4.1


def test_triangle_wall_preserves_doorway_gap_but_closed_panel_blocks_it():
    parts = [
        box("a", "wall", (0, 1, -2), (0.1, 2, 2)),
        box("b", "wall", (0, 1, 2), (0.1, 2, 2)),
        box("c", "wall", (0, 2.2, 0), (0.1, 0.4, 2)),
    ]
    wall = parts[0].model_copy(deep=True)
    wall.position = (0, 0, 0)
    wall.geometry = Geometry(
        vertices=[tuple(v) for part in parts for v in world_vertices(part)],
        colors=[(0.5, 0.5, 0.5)] * 24,
        triangles=[
            tuple(i + 8 * n for i in face)
            for n, part in enumerate(parts)
            for face in part.geometry.triangles
        ],
    )
    assert route_scene(room(wall), request(), "scan")["distance_m"] < 4.1
    panel = box("door", "door", (0, 1, 0), (0.1, 2, 2))
    with pytest.raises(AdapterError, match="No path connects"):
        route_scene(room(wall, panel), request(), "scan")


def test_doorway_selects_reachable_approach_without_claiming_exit():
    door = box("door", "door", (2.9, 1, 0), (0.1, 2, 1.2))
    result = route_scene(room(door), request(end={"object_id": "door"}), "scan")
    assert result["end"]["object_id"] == "door"
    assert 2 < result["end"]["point"][0] < 2.7
    assert "not a confirmed exit" in result["warnings"][1]


def test_edits_rotation_and_scale_change_routes():
    wall = box("wall", "wall", (0, 1, 0), (0.1, 2, 2))
    wall.scale = (1, 1, 3)
    with pytest.raises(AdapterError, match="No path connects"):
        route_scene(room(wall), request(), "scan")
    wall.rotation = (0, pi / 2, 0)
    result = route_scene(
        room(wall), request(start={"point": [-2, 0, 1]}, end={"point": [2, 0, 1]}), "scan"
    )
    assert result["distance_m"] < 4.1
    wall.position = (0, 1, 8)
    assert route_scene(room(wall), request(), "scan")["distance_m"] < 4.1


def test_missing_floor_gap_and_bad_points_are_not_bridged():
    with pytest.raises(AdapterError, match="No usable floor"):
        route_scene(Scene(), request(), "scan")
    scene = Scene(
        objects=[
            box("left", "floor", (-2, -0.05, 0), (2, 0.1, 6)),
            box("right", "floor", (2, -0.05, 0), (2, 0.1, 6)),
        ]
    )
    with pytest.raises(AdapterError, match="No path connects"):
        route_scene(scene, request(), "scan")
    with pytest.raises(AdapterError, match="outside the floor"):
        route_scene(room(), request(start={"point": [8, 0, 0]}), "scan")
    with pytest.raises(AdapterError, match="points on the floor"):
        route_scene(room(), request(start={"point": [0, 1.5, 0]}), "scan")


def test_separate_levels_and_grid_limits():
    scene = room(box("upstairs", "floor", (0, 3, 0), (6, 0.1, 6)))
    with pytest.raises(AdapterError, match="same floor"):
        route_scene(scene, request(end={"point": [2, 3.05, 0]}), "scan")
    with pytest.raises(AdapterError, match="grid limit"):
        route_scene(
            Scene(objects=[box("big", "floor", (0, 0, 0), (100, 0.1, 100))]), request(), "scan"
        )


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "scans"))
    scan = ScanResponse(
        id=uuid4(), name="Routing test", status="degraded", scene=room(), revision=3
    )
    app.state.scan_store.save(scan)
    with TestClient(app) as client:
        yield client, scan


def test_api_routes_and_rejects_stale_or_invalid_requests(client):
    client, scan = client
    url = f"/api/scans/{scan.id}/routes"
    body = request(revision=3).model_dump(exclude_none=True)
    result = client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == 3 and result.json()["scan_id"] == str(scan.id)
    assert len(result.json()["polyline"]) >= 2
    assert client.post(url, json={**body, "revision": 2}).status_code == 409
    assert (
        client.post(url, json={**body, "start": {"point": [0, 0, 0], "object_id": "x"}}).status_code
        == 422
    )
    assert client.post(url, json={**body, "end": {"object_id": "missing"}}).status_code == 422
    assert client.post(f"/api/scans/{uuid4()}/routes", json=body).status_code == 404


def test_api_rechecks_revision_after_planning(client, monkeypatch):
    import app.routes.routing as endpoint

    client, scan = client
    original = endpoint.route_scene

    def mutate(*args):
        result = original(*args)
        scan.revision += 1
        client.app.state.scan_store.save(scan)
        return result

    monkeypatch.setattr(endpoint, "route_scene", mutate)
    assert (
        client.post(
            f"/api/scans/{scan.id}/routes", json=request(revision=3).model_dump()
        ).status_code
        == 409
    )


def test_api_waits_for_finished_scene(client):
    client, scan = client
    scan.status = "processing"
    client.app.state.scan_store.save(scan)
    assert (
        client.post(
            f"/api/scans/{scan.id}/routes", json=request(revision=3).model_dump()
        ).status_code
        == 409
    )
