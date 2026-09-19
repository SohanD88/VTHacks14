"""RF-DETR Nano COCO detector, loaded when a client connects."""

import io
import os
from pathlib import Path
from threading import Lock

from PIL import Image, UnidentifiedImageError

MAX_JPEG_BYTES = 4 * 1024 * 1024
MAX_DIMENSION = 4096
MODEL_CACHE = Path(__file__).resolve().parent.parent / ".model-cache"


class FrameError(ValueError):
    """The client supplied an invalid frame."""


def decode_frame(jpeg: bytes, width: int, height: int) -> Image.Image:
    if not jpeg or len(jpeg) > MAX_JPEG_BYTES:
        raise FrameError("JPEG must be between 1 byte and 4 MB")
    if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
        raise FrameError("Frame dimensions must be between 1 and 4096 pixels")
    try:
        with Image.open(io.BytesIO(jpeg)) as source:
            if source.format != "JPEG":
                raise FrameError("Frame must be a JPEG image")
            if source.size != (width, height):
                raise FrameError("Frame dimensions do not match the JPEG")
            return source.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise FrameError("Could not decode JPEG frame") from exc


class Detector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._model = None
        self.state = "unloaded"
        self.error: str | None = None
        self.threshold = float(os.getenv("DETECTION_CONFIDENCE", "0.5"))
        if not 0 <= self.threshold <= 1:
            raise ValueError("DETECTION_CONFIDENCE must be between 0 and 1")

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            self.state = "loading"
            try:
                import torch
                from rfdetr import RFDETRNano

                # RF-DETR's official checkpoint is cached locally and is not committed.
                os.environ.setdefault("RF_HOME", str(MODEL_CACHE))
                torch.set_num_threads(min(torch.get_num_threads(), 4))
                model = RFDETRNano()
                # The first prediction initializes the inference path. Warm it up
                # before announcing readiness so the browser's frame timer stays valid.
                model.predict(
                    Image.new("RGB", (384, 384)),
                    threshold=self.threshold,
                    include_source_image=False,
                )
                self._model = model
                self.state = "ready"
                self.error = None
            except Exception as exc:
                self.state = "error"
                self.error = str(exc)
                raise

    def detect(self, image: Image.Image) -> list[dict]:
        if self._model is None:
            raise RuntimeError("Detector is not loaded")
        with self._lock:
            result = self._model.predict(
                image, threshold=self.threshold, include_source_image=False
            )
        width, height = image.size
        detections = []
        names = result.data["class_name"]
        for box, name, score in zip(result.xyxy, names, result.confidence):
            confidence = float(score)
            label = str(name)
            if confidence < self.threshold or not label or label == "__background__":
                continue
            x1, y1, x2, y2 = (float(value) for value in box)
            detections.append({
                "label": label,
                "confidence": round(confidence, 3),
                "box": [
                    round(max(0.0, min(1.0, x1 / width)), 4),
                    round(max(0.0, min(1.0, y1 / height)), 4),
                    round(max(0.0, min(1.0, x2 / width)), 4),
                    round(max(0.0, min(1.0, y2 / height)), 4),
                ],
            })
        return detections
