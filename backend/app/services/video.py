"""Bounded decoding, orientation handling and content-based keyframe selection."""

from pathlib import Path

import av
import cv2
import numpy as np

from app.schemas import VideoMetadata

EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}


class ProcessingError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def discover_videos(root: Path) -> list[Path]:
    excluded = {".git", ".venv", "node_modules", ".model-cache", ".spatial-data", "test-results"}
    return sorted(
        p
        for p in root.rglob("*")
        if p.suffix.lower() in EXTENSIONS and not excluded.intersection(p.relative_to(root).parts)
    )


def decoded_timing(path: Path):
    """Count actual frames when the container lacks a trustworthy duration/index."""
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            rate = float(stream.average_rate or stream.guessed_rate or 0)
            first_time = last_time = None
            last_step = 0.0
            count = 0
            for frame in container.decode(stream):
                count += 1
                if frame.width * frame.height > 4096 * 4096 or count > 43_200:
                    raise ProcessingError("Video exceeds the decoding limit. Trim or resize it.")
                if frame.time is not None:
                    timestamp = float(frame.time)
                    if first_time is None:
                        first_time = timestamp
                    if last_time is not None and timestamp > last_time:
                        last_step = timestamp - last_time
                    last_time = timestamp
                    if timestamp - first_time > 180:
                        raise ProcessingError("Video exceeds the 3-minute limit. Trim it.")
            if count == 0:
                raise ProcessingError("Video has no readable frames. Re-export it as H.264 MP4.")
            if first_time is not None and last_time is not None and last_time > first_time:
                duration = last_time - first_time + (last_step or 1 / max(rate, 1))
            elif rate > 0 and np.isfinite(rate):
                duration = count / rate
            else:
                raise ProcessingError("Video timing could not be read. Re-export it as H.264 MP4.")
            return count, count / duration, duration
    except (av.FFmpegError, IndexError, ValueError, OSError) as exc:
        raise ProcessingError(
            "Video cannot be decoded. Try recording again or upload H.264 MP4."
        ) from exc


def metadata(path: Path, filename: str) -> VideoMetadata:
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        if not capture.isOpened():
            raise ProcessingError(
                (
                    "Video cannot be decoded. It may be corrupt or use an unsupported "
                    "codec. Try H.264 MP4."
                )
            )
        fps = capture.get(cv2.CAP_PROP_FPS)
        reported_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        count = int(reported_count) if np.isfinite(reported_count) else 0
        ok, frame = capture.read()
        if not ok:
            raise ProcessingError("Video has no readable frames. Re-export it as H.264 MP4.")
        duration = count / fps if fps > 0 and np.isfinite(fps) else 0
        if frame.shape[0] * frame.shape[1] > 4096 * 4096:
            raise ProcessingError("Video exceeds the 4096×4096 decoding limit. Resize it.")
        if path.suffix.lower() == ".webm" or count <= 0 or duration <= 0:
            count, fps, duration = decoded_timing(path)
        if duration < 1:
            raise ProcessingError(
                "Video is too short. Record at least one second while moving slowly."
            )
        if duration > 180:
            raise ProcessingError(
                "Video exceeds the 3-minute or 4096×4096 decoding limit. Trim or resize it."
            )
        codec = int(capture.get(cv2.CAP_PROP_FOURCC))
        return VideoMetadata(
            filename=filename,
            format=path.suffix.lower()[1:],
            codec="".join(chr((codec >> (8 * i)) & 255) for i in range(4)),
            width=frame.shape[1],
            height=frame.shape[0],
            fps=fps,
            duration=duration,
            total_frames=count,
            rotation=int(capture.get(cv2.CAP_PROP_ORIENTATION_META)),
        )
    finally:
        capture.release()


def extract(path, meta, output, mode, update, check):
    budget = {"quick": 12, "balanced": min(48, max(28, round(meta.duration * 3))), "high": 56}[mode]
    width = {"quick": 384, "balanced": 518, "high": 644}[mode]
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    frames, report, candidates = [], [], []
    previous = None
    decoded = 0
    # Decode sequentially to validate the actual content and count every decoded frame.
    interval = max(1, round(meta.fps / min(8, max(3, budget / meta.duration * 2))))
    try:
        while True:
            check()
            ok, bgr = capture.read()
            if not ok:
                break
            index = decoded
            decoded += 1
            if index % interval:
                report.append({"frame": index, "reason": "sampling_interval"})
                continue
            h, w = bgr.shape[:2]
            rgb = cv2.cvtColor(
                cv2.resize(bgr, (round(w * width / max(w, h)), round(h * width / max(w, h)))),
                cv2.COLOR_BGR2RGB,
            )
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            brightness = float(gray.mean())
            difference = (
                float(np.abs(gray.astype(float) - previous).mean()) if previous is not None else 255
            )
            reason = "candidate"
            if sharpness < 12:
                reason = "blur_or_low_texture"
            elif brightness < 12 or brightness > 248:
                reason = "poor_exposure"
            elif difference < 1.5:
                reason = "duplicate"
            item = dict(
                frame=index,
                sharpness=round(sharpness, 2),
                brightness=round(brightness, 2),
                difference=round(difference, 2),
                reason=reason,
            )
            report.append(item)
            if reason == "candidate":
                candidates.append((index, rgb, sharpness, item))
                previous = gray.astype(float)
            update(
                stage="decoding", progress=min(20, decoded / meta.total_frames * 20), frames=decoded
            )
    finally:
        capture.release()
    if len(candidates) < 2:
        raise ProcessingError(
            (
                "Too few usable frames: blur, poor exposure or no camera movement."
                " Record slowly with good light and overlapping views."
            )
        )
    # Temporal bins retain the sharpest observation, adapting to each video's quality.
    for bucket in np.array_split(np.arange(len(candidates)), min(budget, len(candidates))):
        best = max(bucket, key=lambda i: candidates[i][2])
        n, rgb, _, item = candidates[best]
        item["reason"] = "accepted"
        frames.append((n, rgb))
        cv2.imwrite(str(output / f"frame-{n:06}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    for item in report:
        if item["reason"] == "candidate":
            item["reason"] = "keyframe_budget"
    return frames, report, decoded
