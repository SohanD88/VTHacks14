"""Conservative multi-view motion evidence, independent of learned depth scale."""

import cv2
import numpy as np


def geometric_residuals(first, second, p0, p1):
    """Pixel residuals under the known relative camera motion.

    Use Sampson distance for translation and rotation-only reprojection for a
    negligible baseline. Epipolar consistency alone cannot detect every motion.
    """
    a, b = first["pose"], second["pose"]
    rotation = b[:3, :3].T @ a[:3, :3]
    translation = b[:3, :3].T @ (a[:3, 3] - b[:3, 3])
    x0, x1 = np.c_[p0, np.ones(len(p0))], np.c_[p1, np.ones(len(p1))]
    if np.linalg.norm(translation) < 0.015:
        homography = second["K"] @ rotation @ np.linalg.inv(first["K"])
        projected = x0 @ homography.T
        predicted = projected[:, :2] / np.maximum(projected[:, 2:], 1e-8)
        return np.linalg.norm(predicted - p1, axis=1), "rotation"
    x, y, z = translation
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    fundamental = np.linalg.inv(second["K"]).T @ cross @ rotation @ np.linalg.inv(first["K"])
    line1, line0 = x0 @ fundamental.T, x1 @ fundamental
    numerator = np.sum(x1 * line1, axis=1)
    denominator = (line1[:, :2] ** 2).sum(axis=1) + (line0[:, :2] ** 2).sum(axis=1)
    return np.abs(numerator) / np.sqrt(np.maximum(denominator, 1e-12)), "epipolar"


def inside(view, pixels):
    mask = cv2.erode(view["mask"].astype(np.uint8), np.ones((3, 3), np.uint8))
    xy = np.rint(pixels / view["step"]).astype(int)
    valid = (
        (xy[:, 0] >= 0) & (xy[:, 0] < mask.shape[1]) & (xy[:, 1] >= 0) & (xy[:, 1] < mask.shape[0])
    )
    result = np.zeros(len(pixels), bool)
    result[valid] = mask[xy[valid, 1], xy[valid, 0]] > 0
    return result


class MotionAnalyzer:
    def __init__(self, features):
        self.features = features
        self.pairs = list(zip(sorted(features)[:-1], sorted(features)[1:]))
        self.cache = {}

    def pair(self, frames):
        if frames in self.cache:
            return self.cache[frames]
        first, second = (self.features[f] for f in frames)
        matcher = cv2.BFMatcher()
        forward = matcher.knnMatch(first["descriptors"], second["descriptors"], k=2)
        reverse = matcher.knnMatch(second["descriptors"], first["descriptors"], k=2)
        backward = {
            a.queryIdx: a.trainIdx
            for pair in reverse
            if len(pair) == 2
            for a, b in [pair]
            if a.distance < 0.65 * b.distance
        }
        matches = [
            (a.queryIdx, a.trainIdx)
            for pair in forward
            if len(pair) == 2
            for a, b in [pair]
            if a.distance < 0.65 * b.distance and backward.get(a.trainIdx) == a.queryIdx
        ]
        if len(matches) < 36:
            self.cache[frames] = None
            return None
        indices = np.array(matches)
        p0, p1 = first["pixels"][indices[:, 0]], second["pixels"][indices[:, 1]]
        errors, method = geometric_residuals(first, second, p0, p1)
        world = first["xyz"][indices[:, 0]] @ first["pose"][:3, :3].T + first["pose"][:3, 3]
        camera = (world - second["pose"][:3, 3]) @ second["pose"][:3, :3]
        projected = camera @ second["K"].T
        predicted = projected[:, :2] / np.maximum(projected[:, 2:], 1e-8)
        reprojection = np.linalg.norm(predicted - p1, axis=1)
        value = dict(p0=p0, p1=p1, errors=errors, reprojection=reprojection, method=method)
        self.cache[frames] = value
        return value

    def assess(self, views):
        by_frame = {}
        for view in views:
            frame = view["frame"]
            if frame not in by_frame or view["mask"].sum() > by_frame[frame]["mask"].sum():
                by_frame[frame] = view
        evidence = []
        streak = longest = 0
        for frames in self.pairs:
            if not all(frame in by_frame for frame in frames):
                streak = 0
                continue
            pair = self.pair(frames)
            if pair is None:
                streak = 0
                continue
            left, right = (
                inside(by_frame[frames[0]], pair["p0"]),
                inside(by_frame[frames[1]], pair["p1"]),
            )
            foreground, background = left & right, ~(left | right)
            if foreground.sum() < 6 or background.sum() < 30:
                streak = 0
                continue
            background_error = float(np.percentile(pair["errors"][background], 90))
            if background_error > 2.0:
                streak = 0
                continue
            threshold = max(4.0, background_error * 2.5)
            errors = pair["errors"][foreground]
            fraction = float((errors > threshold).mean())
            reprojection = float(np.median(pair["reprojection"][foreground]))
            moving = fraction >= 0.75 and reprojection > 6.0
            streak = streak + 1 if moving else 0
            longest = max(longest, streak)
            evidence.append(
                dict(
                    frames=list(frames),
                    matches=int(foreground.sum()),
                    method=pair["method"],
                    background_p90_px=round(background_error, 3),
                    threshold_px=round(threshold, 3),
                    median_residual_px=round(float(np.median(errors)), 3),
                    reprojection_px=round(reprojection, 3),
                    outlier_fraction=round(fraction, 3),
                    moving=moving,
                )
            )
        status = (
            "moving_candidate"
            if longest >= 2
            else "consistent"
            if len(evidence) >= 2 and not any(e["moving"] for e in evidence)
            else "insufficient_evidence"
        )
        return dict(status=status, consecutive_motion_pairs=longest, pairs=evidence)
