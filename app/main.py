"""FastAPI demo page and version 1 detection WebSocket."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .detector import Detector, FrameError, decode_frame

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Live object detection")
app.state.detector = Detector()
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health() -> dict:
    detector = app.state.detector
    return {
        "status": "ok", "engine": "rf-detr-nano",
        "model": detector.state, "error": detector.error,
    }


def parse_header(raw: str) -> tuple[int, int, int]:
    try:
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


@app.websocket("/ws/detect")
async def detect_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    detector = app.state.detector
    try:
        await websocket.send_json({"type": "status", "status": "loading"})
        try:
            await asyncio.to_thread(detector.load)
        except Exception:
            await websocket.send_json({"type": "error", "message": f"Model could not load: {detector.error}"})
            await websocket.close(code=1011)
            return
        await websocket.send_json({"type": "status", "status": "ready"})
        while True:
            # Request/response ordering provides one in-flight frame per client.
            header_message = await websocket.receive()
            if header_message.get("type") == "websocket.disconnect":
                return
            if header_message.get("text") is None:
                await websocket.send_json({"type": "error", "message": "Expected JSON frame header"})
                continue
            try:
                frame_id, width, height = parse_header(header_message["text"])
            except FrameError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue
            image_message = await websocket.receive()
            if image_message.get("type") == "websocket.disconnect":
                return
            jpeg = image_message.get("bytes")
            if jpeg is None:
                await websocket.send_json({"type": "error", "message": "Expected binary JPEG after frame header"})
                continue
            try:
                image = decode_frame(jpeg, width, height)
                detections = await asyncio.to_thread(detector.detect, image)
            except FrameError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue
            except Exception:
                await websocket.send_json({"type": "error", "message": "Frame inference failed"})
                continue
            await websocket.send_json({
                "type": "detections", "id": frame_id, "width": width,
                "height": height, "detections": detections,
            })
    except WebSocketDisconnect:
        return
