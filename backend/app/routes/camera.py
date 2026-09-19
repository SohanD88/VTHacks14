"""One frame header + binary JPEG in, normalized detections out. Frames are not stored."""

import asyncio
import json
import logging
from time import perf_counter

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.detection import FrameError, decode_frame

router = APIRouter(prefix="/api/camera", tags=["camera"])
logger = logging.getLogger("spatial.camera")


def parse_header(raw: str) -> tuple[int, int, int]:
    try:
        if len(raw) > 1024:
            raise ValueError
        header = json.loads(raw)
        if not isinstance(header, dict) or header.get("type") != "frame":
            raise ValueError
        frame_id, width, height = header["id"], header["width"], header["height"]
        if any(type(value) is not int for value in (frame_id, width, height)):
            raise ValueError
        if frame_id < 0 or not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError
        return frame_id, width, height
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise FrameError("Expected frame header with integer id, width, and height") from exc


@router.websocket("/detect")
async def detect_socket(websocket: WebSocket) -> None:
    # CORS middleware does not validate WebSocket origins.
    origin = websocket.headers.get("origin")
    if origin and origin not in websocket.app.state.settings.cors_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    detector = websocket.app.state.detector
    try:
        await websocket.send_json({"type": "status", "status": "loading"})
        try:
            await asyncio.to_thread(detector.load)
        except Exception:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "model_load_failed",
                    "message": "Detection model could not load. Check backend logs, then retry.",
                    "fatal": True,
                }
            )
            await websocket.close(code=1011)
            return
        await websocket.send_json({"type": "status", "status": "ready"})
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            try:
                if message.get("text") is None:
                    raise FrameError("Expected JSON frame header")
                frame_id, width, height = parse_header(message["text"])
                image_message = await asyncio.wait_for(websocket.receive(), timeout=15)
                if image_message["type"] == "websocket.disconnect":
                    return
                if image_message.get("bytes") is None:
                    raise FrameError("Expected binary JPEG after frame header")
                started = perf_counter()

                # Decode and inference both stay off the API event loop.
                def process():
                    with decode_frame(image_message["bytes"], width, height) as image:
                        return detector.detect(image)

                detections = await asyncio.to_thread(process)
                await websocket.send_json(
                    {
                        "type": "detections",
                        "id": frame_id,
                        "width": width,
                        "height": height,
                        "detections": detections,
                        "processing_ms": round((perf_counter() - started) * 1000),
                    }
                )
            except FrameError as exc:
                await websocket.send_json({"type": "error", "message": str(exc), "fatal": False})
            except TimeoutError:
                await websocket.close(code=1008, reason="JPEG frame timed out")
                return
            except WebSocketDisconnect:
                return
            except Exception:
                logger.exception("Camera frame inference failed")
                await websocket.send_json(
                    {"type": "error", "message": "Frame inference failed", "fatal": False}
                )
    except WebSocketDisconnect:
        return
