"""Save orientation-correct contact sheets and metadata for discovered input videos."""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.video import discover_videos, metadata  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / "test-results" / "video-inspection"
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for path in discover_videos(root):
        info = metadata(path, path.name)
        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        canvas = Image.new("RGB", (960, 1350), "#15191e")
        draw = ImageDraw.Draw(canvas)
        indices = np.linspace(0, info.total_frames - 1, 12, dtype=int)
        samples = []
        for i, frame in enumerate(indices):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame))
            ok, bgr = capture.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            image.thumbnail((236, 420))
            x, y = (i % 4) * 240, (i // 4) * 450
            canvas.paste(image, (x + (240 - image.width) // 2, y + 25))
            draw.text((x + 5, y + 5), f"Frame {frame} / {frame / info.fps:.2f}s", fill="white")
            gray = cv2.cvtColor(cv2.resize(rgb, (292, 518)), cv2.COLOR_RGB2GRAY)
            samples.append(
                {
                    "frame": int(frame),
                    "brightness": round(float(gray.mean()), 2),
                    "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
                }
            )
        capture.release()
        canvas.save(output / f"{path.stem}-upright-contact.jpg", quality=90)
        report.append(
            {
                **info.model_dump(),
                "relative_path": str(path.relative_to(root)),
                "aspect_ratio": info.width / info.height,
                "samples": samples,
            }
        )
    (output / "metadata.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
