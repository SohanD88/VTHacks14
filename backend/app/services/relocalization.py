"""Recover missed views from mutually matched, already localized image evidence."""

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def estimate(reference, target, matches):
    """A candidate needs distributed image support, positive depth, and bounded error."""
    source_ids, target_ids = np.array(matches).T
    pose, K = reference["pose"], target["K"]
    xyz = reference["xyz"][source_ids] @ pose[:3, :3].T + pose[:3, 3]
    pixels = target["pixels"][target_ids]
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        xyz,
        pixels,
        K,
        None,
        iterationsCount=300,
        reprojectionError=3.0,
        confidence=0.999,
        flags=cv2.SOLVEPNP_EPNP,
    )
    if not ok or inliers is None or len(inliers) < 20 or len(inliers) / len(matches) < 0.5:
        return None
    ids = inliers[:, 0]
    extent = np.ptp(pixels[ids], axis=0) / (2 * K[:2, 2])
    if min(extent) < 0.15 or np.prod(extent) < 0.06:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(xyz[ids], pixels[ids], K, None, rvec, tvec)
    rotation = cv2.Rodrigues(rvec)[0]
    camera = xyz[ids] @ rotation.T + tvec[:, 0]
    if np.any(camera[:, 2] <= 0):
        return None
    projected = cv2.projectPoints(xyz[ids], rvec, tvec, K, None)[0][:, 0]
    errors = np.linalg.norm(projected - pixels[ids], axis=1)
    if np.median(errors) > 2 or np.percentile(errors, 90) > 3.5:
        return None
    candidate = np.eye(4)
    candidate[:3, :3] = rotation.T
    candidate[:3, 3] = -rotation.T @ tvec[:, 0]
    if np.linalg.norm(candidate[:3, 3] - pose[:3, 3]) > 2.5:
        return None
    scale = float(np.median(camera[:, 2] / target["xyz"][target_ids[ids], 2]))
    if not 0.65 < scale < 1.5:
        return None
    return dict(
        pose=candidate,
        scale=scale,
        reference=reference["frame"],
        matches=len(matches),
        inliers=len(ids),
        reprojection_px=float(errors.mean()),
    )


def recover_views(views, pending, check=lambda: None):
    """Require agreement from two references; never initialize a disconnected submap.

    At most three passes allow a supported recovered view to help an adjacent view.
    Every recovery remains connected to the original accepted coordinate system.
    """
    references = list(views)
    remaining = list(pending)
    recovered, report = [], []
    matcher = cv2.BFMatcher()
    cache = {}
    for pass_index in range(3):
        additions = []
        for target in remaining:
            check()
            if target["descriptors"] is None or len(target["pixels"]) < 20:
                continue
            pairs = []
            for reference in references:
                check()
                key = (reference["frame"], target["frame"])
                if key not in cache:
                    forward = matcher.knnMatch(reference["descriptors"], target["descriptors"], k=2)
                    backward = matcher.knnMatch(
                        target["descriptors"], reference["descriptors"], k=2
                    )
                    reverse = {
                        pair[0].queryIdx: pair[0].trainIdx
                        for pair in backward
                        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance
                    }
                    cache[key] = [
                        (pair[0].queryIdx, pair[0].trainIdx)
                        for pair in forward
                        if len(pair) == 2
                        and pair[0].distance < 0.75 * pair[1].distance
                        and reverse.get(pair[0].trainIdx) == pair[0].queryIdx
                    ]
                matches = cache[key]
                if len(matches) >= 20:
                    pairs.append((reference, matches))
            candidates = []
            for reference, matches in sorted(pairs, key=lambda pair: -len(pair[1]))[:6]:
                candidate = estimate(reference, target, matches)
                if candidate is not None:
                    candidates.append(candidate)
            supported = []
            for candidate in candidates:
                agrees = []
                for other in candidates:
                    delta = candidate["pose"][:3, 3] - other["pose"][:3, 3]
                    rotation = candidate["pose"][:3, :3].T @ other["pose"][:3, :3]
                    if (
                        np.linalg.norm(delta) <= 0.2
                        and Rotation.from_matrix(rotation).magnitude() <= 0.06
                        and abs(np.log(candidate["scale"] / other["scale"])) <= 0.12
                    ):
                        agrees.append(other)
                if len(agrees) >= 2:
                    supported.append((candidate, agrees))
            if not supported:
                continue
            best, support = max(supported, key=lambda pair: pair[0]["inliers"])
            view = dict(target, pose=best["pose"], xyz=target["xyz"] * best["scale"])
            additions.append(view)
            report.append(
                dict(
                    frame=target["frame"],
                    pass_index=pass_index,
                    method="multiview_relocalization",
                    depth_scale_alignment=best["scale"],
                    reference_frames=[c["reference"] for c in support],
                    inliers=best["inliers"],
                    matches=best["matches"],
                    reprojection_px=best["reprojection_px"],
                )
            )
        if not additions:
            break
        recovered.extend(additions)
        references.extend(additions)
        done = {view["frame"] for view in additions}
        remaining = [view for view in remaining if view["frame"] not in done]
    return recovered, report
