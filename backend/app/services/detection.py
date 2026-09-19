"""RF-DETR Nano camera inference adapted from SDObjectDetection (e646087)."""

import io
import logging
import math
import os
from pathlib import Path
from threading import Lock

from PIL import Image, UnidentifiedImageError

MAX_JPEG_BYTES = 4 * 1024 * 1024
MAX_DIMENSION = 4096
logger = logging.getLogger("spatial.camera")


class FrameError(ValueError):
    """Invalid client-supplied image or frame metadata."""


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


class CameraDetector:
    def __init__(self, threshold: float, cache: Path):
        self.threshold = threshold
        self.cache = cache
        self.state = "unloaded"
        self._model = None
        self._lock = Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            self.state = "loading"
            try:
                import torch

                # Configure the local checkpoint cache before importing the inference stack.
                os.environ.setdefault("RF_HOME", str(self.cache))
                from rfdetr import RFDETRNano

                torch.set_num_threads(min(torch.get_num_threads(), 4))
                model = RFDETRNano()
                model.predict(
                    Image.new("RGB", (384, 384)),
                    threshold=self.threshold,
                    include_source_image=False,
                )
                self._model = model
                self.state = "ready"
                logger.info("RF-DETR Nano ready threshold=%s", self.threshold)
            except Exception:
                self.state = "error"
                logger.exception("RF-DETR Nano could not load")
                raise

    def detect(self, image: Image.Image) -> list[dict]:
        with self._lock:
            if self._model is None:
                raise RuntimeError("Detector is not loaded")
            result = self._model.predict(
                image, threshold=self.threshold, include_source_image=False
            )
        width, height = image.size
        detections = []
        for box, name, score in zip(result.xyxy, result.data["class_name"], result.confidence):
            confidence, label = float(score), str(name)
            coordinates = [float(value) for value in box]
            if (
                not math.isfinite(confidence)
                or confidence < self.threshold
                or not label
                or label == "__background__"
                or not all(math.isfinite(value) for value in coordinates)
            ):
                continue
            normalized = [
                round(max(0.0, min(1.0, value / size)), 4)
                for value, size in zip(coordinates, [width, height, width, height])
            ]
            if normalized[2] <= normalized[0] or normalized[3] <= normalized[1]:
                continue
            detections.append(
                {"label": label, "confidence": round(confidence, 3), "box": normalized}
            )
        return detections
