"""Local pretrained metric depth and broad ADE20K semantic segmentation."""

from threading import Lock
from time import perf_counter

import cv2
import numpy as np

from app.services.detection import CameraDetector
from app.services.video import ProcessingError

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
SEMANTIC_MODEL = "nvidia/segformer-b2-finetuned-ade-512-512"


class VisionModels:
    def __init__(self, cache):
        self.cache = cache
        self.ready = False
        self.lock = Lock()
        self.device = "cpu"
        self.detector = CameraDetector(0.45, cache)

    def load(self):
        with self.lock:
            if self.ready:
                return
            try:
                import torch
                from transformers import (
                    AutoImageProcessor,
                    AutoModelForDepthEstimation,
                    SegformerForSemanticSegmentation,
                )

                torch.set_num_threads(4)
                self.device = (
                    "cuda"
                    if torch.cuda.is_available()
                    else "mps"
                    if torch.backends.mps.is_available()
                    else "cpu"
                )
                options = {"cache_dir": str(self.cache / "huggingface")}
                self.dp = AutoImageProcessor.from_pretrained(DEPTH_MODEL, **options)
                self.dm = (
                    AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL, **options)
                    .eval()
                    .to(self.device)
                )
                self.sp = AutoImageProcessor.from_pretrained(SEMANTIC_MODEL, **options)
                self.sm = (
                    SegformerForSemanticSegmentation.from_pretrained(SEMANTIC_MODEL, **options)
                    .eval()
                    .to(self.device)
                )
                self.labels = self.sm.config.id2label
                self.detector.load()
                self.ready = True
            except (OSError, ImportError, RuntimeError) as exc:
                raise ProcessingError(
                    (
                        "Depth/segmentation models could not load. Check installed depende"
                        "ncies, internet access for first download, and available memory; "
                        "then retry."
                    )
                ) from exc

    def infer(self, rgb):
        import torch
        from PIL import Image

        image = Image.fromarray(rgb)
        h, w = rgb.shape[:2]
        with self.lock, torch.inference_mode():
            started = perf_counter()
            inputs = self.dp(images=image, return_tensors="pt").to(self.device)
            depth = self.dm(**inputs).predicted_depth
            depth = (
                torch.nn.functional.interpolate(
                    depth[:, None], size=(h, w), mode="bicubic", align_corners=False
                )[0, 0]
                .cpu()
                .numpy()
            )
            depth_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            logits = self.sm(**self.sp(images=image, return_tensors="pt").to(self.device)).logits
            probabilities = torch.nn.functional.interpolate(
                logits, size=(h, w), mode="bilinear", align_corners=False
            ).softmax(1)
            confidence, labels = probabilities.max(1)
            labels = labels[0].cpu().numpy().astype(np.uint8)
            confidence = confidence[0].cpu().numpy()
            detections = self.detector.detect(image)
            semantic_ms = (perf_counter() - started) * 1000
        if not np.isfinite(depth).all() or np.median(depth) <= 0:
            raise ProcessingError(
                "Depth estimation returned invalid values. Try a brighter recording or quick mode."
            )
        return np.clip(depth, 0.15, 20), labels, confidence, depth_ms, semantic_ms, detections

    def diagnostics(self, rgb, depth, labels, confidence, output, frame, detections=()):
        from PIL import Image, ImageDraw

        cv2.imwrite(
            str(output / f"depth-{frame:06}.png"),
            cv2.applyColorMap(np.uint8(np.clip(depth / 10, 0, 1) * 255), cv2.COLORMAP_TURBO),
        )
        np.save(output / f"depth-{frame:06}.npy", depth)
        cv2.imwrite(str(output / f"mask-{frame:06}.png"), labels)
        palette = np.array(
            [[(i * 67) % 255, (i * 131) % 255, (i * 197) % 255] for i in range(150)], dtype=np.uint8
        )
        overlay = Image.fromarray((rgb * 0.5 + palette[labels] * 0.5).astype(np.uint8))
        draw = ImageDraw.Draw(overlay)
        y = 2
        for k, count in sorted(zip(*np.unique(labels, return_counts=True)), key=lambda p: -p[1])[
            :10
        ]:
            score = float(confidence[labels == k].mean())
            draw.text(
                (3, y),
                f"{self.labels[int(k)]}: {score:.2f}",
                fill="white",
                stroke_width=1,
                stroke_fill="black",
            )
            y += 14
        overlay.save(output / f"segmentation-{frame:06}.jpg")
        evidence = Image.fromarray(rgb)
        draw = ImageDraw.Draw(evidence)
        h, w = rgb.shape[:2]
        for detection in detections:
            left, top, right, bottom = detection["box"]
            box = (left * w, top * h, right * w, bottom * h)
            draw.rectangle(box, outline="cyan", width=2)
            draw.text(
                (left * w, top * h),
                f"{detection['label']} {detection['confidence']:.2f}",
                fill="white",
                stroke_fill="black",
                stroke_width=1,
            )
        evidence.save(output / f"detection-{frame:06}.jpg")
