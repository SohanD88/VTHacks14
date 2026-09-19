"""Optional real-model smoke test: uv run python scripts/smoke_camera.py [image.jpg].

Downloads official model weights on first use. Uses a supplied image or a blank
synthetic frame; never opens a physical camera. Unit tests use a stub instead.
"""

import io
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import create_app  # noqa: E402

image = (
    Image.open(sys.argv[1]).convert("RGB") if len(sys.argv) > 1 else Image.new("RGB", (640, 480))
)
image.thumbnail((640, 640))
buffer = io.BytesIO()
image.save(buffer, "JPEG", quality=75)
with TestClient(create_app()) as client, client.websocket_connect("/api/camera/detect") as socket:
    assert socket.receive_json()["status"] == "loading"
    status = socket.receive_json()
    if status.get("status") != "ready":
        raise RuntimeError(status)
    socket.send_json({"type": "frame", "id": 1, "width": image.width, "height": image.height})
    socket.send_bytes(buffer.getvalue())
    result = socket.receive_json()
    assert result["type"] == "detections" and result["id"] == 1
    print(json.dumps(result, indent=2))
