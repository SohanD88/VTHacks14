from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.scans import get_reconstruction


@pytest.fixture
def client():
    with TestClient(create_app(Settings(max_stored_scans=2))) as client:
        yield client


def test_health_and_real_scan_lifecycle(client):
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.post("/api/scans", json={"name": "  Test room  ", "preset": "office"})
    assert response.status_code == 201
    scan = response.json()
    assert scan["name"] == "Test room"
    assert scan["processing_mode"] == "mock"
    assert scan["stats"]["objects"] == len(scan["scene"]["objects"]) == 6
    assert sum(d["count"] for d in scan["detections"]) == scan["stats"]["objects"]
    assert client.get(f"/api/scans/{scan['id']}").json() == scan
    assert response.headers["x-request-id"]


def test_presets_change_scene_and_scan_ids(client):
    office = client.post("/api/scans", json={"name": "Office", "preset": "office"}).json()
    corridor = client.post("/api/scans", json={"name": "Hall", "preset": "corridor"}).json()
    assert office["id"] != corridor["id"]
    assert office["scene"] != corridor["scene"]
    assert corridor["stats"]["objects"] == 4


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": " "},
        {"name": "x" * 81},
        {"name": "Scan", "preset": "unknown"},
        {"name": "Scan", "source": "camera"},
        {"name": "Scan", "extra": True},
    ],
)
def test_validation_is_structured(client, body):
    response = client.post("/api/scans", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert response.json()["error"]["fields"]


def test_missing_scans_and_bounded_storage(client):
    first = client.post("/api/scans", json={"name": "First"}).json()
    for name in ["Second", "Third"]:
        client.post("/api/scans", json={"name": name})
    for scan_id in [first["id"], str(uuid4())]:
        response = client.get(f"/api/scans/{scan_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_cors(client):
    response = client.options(
        "/api/scans",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options(
        "/api/scans",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_unexpected_errors_are_safe_and_retryable(client):
    class BrokenService:
        def reconstruct(self, request):
            raise RuntimeError("Internal details must not leak")

    client.app.dependency_overrides[get_reconstruction] = lambda: BrokenService()
    response = client.post(
        "/api/scans", json={"name": "Failure"}, headers={"Origin": "http://localhost:5173"}
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Internal details" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    client.app.dependency_overrides.clear()
    assert client.post("/api/scans", json={"name": "Retry"}).status_code == 201
