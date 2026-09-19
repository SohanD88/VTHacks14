import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.routes.camera import parse_header
from app.services.detection import CameraDetector, FrameError, decode_frame


class StubDetector:
    state = "unloaded"

    def load(self):
        self.state = "ready"

    def detect(self, image):
        assert image.size == (32, 24)
        return [{"label": "cup", "confidence": 0.91, "box": [0.1, 0.2, 0.5, 0.8]}]


@pytest.fixture
def client():
    app = create_app(Settings())
    app.state.detector = StubDetector()
    with TestClient(app) as client:
        yield client


def jpeg_bytes(format="JPEG"):
    data = io.BytesIO()
    Image.new("RGB", (32, 24), "blue").save(data, format)
    return data.getvalue()


def ready(socket):
    assert socket.receive_json() == {"type": "status", "status": "loading"}
    assert socket.receive_json() == {"type": "status", "status": "ready"}


def send_frame(socket, data=None):
    socket.send_json({"type": "frame", "id": 7, "width": 32, "height": 24})
    socket.send_bytes(jpeg_bytes() if data is None else data)


def test_detection_protocol_and_scan_coexist(client):
    assert client.get("/api/health").json()["camera"]["model"] == "unloaded"
    with client.websocket_connect("/api/camera/detect") as socket:
        ready(socket)
        send_frame(socket)
        response = socket.receive_json()
        assert response["type"] == "detections"
        assert response["id"] == 7
        assert response["width"] == 32 and response["height"] == 24
        assert response["detections"] == [
            {"label": "cup", "confidence": 0.91, "box": [0.1, 0.2, 0.5, 0.8]}
        ]
        assert response["processing_ms"] >= 0
        assert client.get("/api/health").json()["camera"]["model"] == "ready"
        assert client.post("/api/scans", json={"name": "Still works"}).status_code == 201


def test_bad_frames_recover_without_reconnecting(client):
    with client.websocket_connect("/api/camera/detect") as socket:
        ready(socket)
        for invalid in [b"not jpeg", jpeg_bytes("PNG")]:
            send_frame(socket, invalid)
            assert socket.receive_json()["type"] == "error"
        socket.send_bytes(b"missing header")
        assert socket.receive_json()["type"] == "error"
        socket.send_text("not JSON")
        assert socket.receive_json()["type"] == "error"
        send_frame(socket)
        assert socket.receive_json()["id"] == 7


@pytest.mark.parametrize(
    "header",
    [
        None,
        [],
        {},
        {"type": "frame", "id": True, "width": 32, "height": 24},
        {"type": "frame", "id": 1, "width": 5000, "height": 24},
    ],
)
def test_header_validation(header):
    with pytest.raises(FrameError):
        parse_header(json.dumps(header))


def test_dimension_and_size_validation():
    for data, width, height in [
        (jpeg_bytes(), 33, 24),
        (b"x" * (4 * 1024 * 1024 + 1), 32, 24),
        (b"", 32, 24),
    ]:
        with pytest.raises(FrameError):
            decode_frame(data, width, height)


def test_load_failure_reports_fatal_error(client):
    def fail():
        raise RuntimeError("Internal model failure")

    client.app.state.detector.load = fail
    with client.websocket_connect("/api/camera/detect") as socket:
        assert socket.receive_json()["status"] == "loading"
        response = socket.receive_json()
        assert response["fatal"] is True
        assert response["code"] == "model_load_failed"
        assert "Internal model failure" not in response["message"]
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


def test_untrusted_websocket_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/camera/detect", headers={"origin": "https://untrusted.example"}
        ):
            pass


def test_allowed_websocket_origin(client):
    with client.websocket_connect(
        "/api/camera/detect", headers={"origin": "http://127.0.0.1:5173"}
    ) as socket:
        ready(socket)


def test_prediction_normalizes_and_filters(tmp_path):
    class FakeModel:
        def predict(self, image, *, threshold, include_source_image):
            assert threshold == 0.5 and include_source_image is False
            return SimpleNamespace(
                xyxy=[[20, 10, 100, 80], [0, 0, 20, 20], [-20, 0, 300, 200], [0, 0, 10, 10]],
                confidence=[0.91, 0.99, 0.8, 0.2],
                data={"class_name": ["cup", "__background__", "chair", "bottle"]},
            )

    detector = CameraDetector(0.5, tmp_path)
    detector._model = FakeModel()
    assert detector.detect(Image.new("RGB", (200, 100))) == [
        {"label": "cup", "confidence": 0.91, "box": [0.1, 0.1, 0.5, 0.8]},
        {"label": "chair", "confidence": 0.8, "box": [0, 0, 1, 1]},
    ]
