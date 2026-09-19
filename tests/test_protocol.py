import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


class StubDetector:
    state = "unloaded"
    error = None

    def load(self):
        self.state = "ready"

    def detect(self, image):
        assert image.size == (32, 24)
        return [{"label": "cup", "confidence": 0.91, "box": [0.1, 0.2, 0.5, 0.8]}]


def jpeg_bytes():
    data = io.BytesIO()
    Image.new("RGB", (32, 24), "blue").save(data, "JPEG")
    return data.getvalue()


def test_websocket_detection_contract():
    original = app.state.detector
    app.state.detector = StubDetector()
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").json()["model"] == "unloaded"
            assert client.get("/").status_code == 200
            with client.websocket_connect("/ws/detect") as socket:
                assert socket.receive_json() == {"type": "status", "status": "loading"}
                assert socket.receive_json() == {"type": "status", "status": "ready"}
                socket.send_text(json.dumps({"type": "frame", "id": 7, "width": 32, "height": 24}))
                socket.send_bytes(jpeg_bytes())
                assert socket.receive_json() == {
                    "type": "detections", "id": 7, "width": 32, "height": 24,
                    "detections": [{"label": "cup", "confidence": 0.91, "box": [0.1, 0.2, 0.5, 0.8]}],
                }
    finally:
        app.state.detector = original


def test_invalid_frame_does_not_end_session():
    original = app.state.detector
    app.state.detector = StubDetector()
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/detect") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_text(json.dumps({"type": "frame", "id": 1, "width": 32, "height": 24}))
            socket.send_bytes(b"not a jpeg")
            assert socket.receive_json()["type"] == "error"
            socket.send_text(json.dumps({"type": "frame", "id": 2, "width": 32, "height": 24}))
            socket.send_bytes(jpeg_bytes())
            assert socket.receive_json()["id"] == 2
    finally:
        app.state.detector = original
