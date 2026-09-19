"""Bounded joint RGB-D registration using overlapping and revisited feature matches.

The origin stays fixed. Robust 3D and symmetric image reprojection residuals refine
accepted poses and per-view depth scale; no pose is invented for an untracked view.
"""

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation


def refine_views(views, check=lambda: None):
    """Views contain pixels, descriptors, xyz, K and camera-to-world pose."""
    count = len(views)
    report = {"accepted": False, "views": count, "edges": 0, "matches": 0}
    if count < 3:
        report["reason"] = "Too few localized views for joint refinement"
        return [v["pose"].copy() for v in views], np.ones(count), report
    first, second, left, right, xy_left, xy_right = [], [], [], [], [], []
    matcher = cv2.BFMatcher()
    for j in range(1, count):
        check()
        # Dense local overlap plus regularly spaced older views allows return-view edges.
        candidates = sorted(set(range(max(0, j - 4), j)) | set(range(0, j - 4, 4)))
        for i in candidates:
            a, b = views[i], views[j]
            matches = matcher.knnMatch(a["descriptors"], b["descriptors"], k=2)
            good = [p[0] for p in matches if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
            if len(good) < 16:
                continue
            good = sorted(good, key=lambda m: m.distance)[:100]
            ia, ib = np.array([m.queryIdx for m in good]), np.array([m.trainIdx for m in good])
            pa, pb = a["xyz"][ia], b["xyz"][ib]
            wa = pa @ a["pose"][:3, :3].T + a["pose"][:3, 3]
            wb = pb @ b["pose"][:3, :3].T + b["pose"][:3, 3]
            # Initial-pose gating rejects repeated-texture aliases, not all depth disagreement.
            qa = (wb - a["pose"][:3, 3]) @ a["pose"][:3, :3]
            qb = (wa - b["pose"][:3, 3]) @ b["pose"][:3, :3]
            ea = np.linalg.norm(project(qa, a["K"]) - a["pixels"][ia], axis=1)
            eb = np.linalg.norm(project(qb, b["K"]) - b["pixels"][ib], axis=1)
            valid = (ea < 12) & (eb < 12) & (qa[:, 2] > 0) & (qb[:, 2] > 0)
            if valid.sum() < 14:
                continue
            pa, pb, ia, ib = pa[valid], pb[valid], ia[valid], ib[valid]
            first.extend([i] * len(pa))
            second.extend([j] * len(pa))
            left.extend(pa)
            right.extend(pb)
            xy_left.extend(a["pixels"][ia])
            xy_right.extend(b["pixels"][ib])
            report["edges"] += 1
    if not first:
        report["reason"] = "No verified overlapping feature edges"
        return [v["pose"].copy() for v in views], np.ones(count), report
    ia, ib = np.array(first), np.array(second)
    left, right = np.array(left), np.array(right)
    xy_left, xy_right = np.array(xy_left), np.array(xy_right)
    initial = np.array(
        [
            np.r_[Rotation.from_matrix(v["pose"][:3, :3]).as_rotvec(), v["pose"][:3, 3], 0.0]
            for v in views
        ]
    )
    intrinsics = np.array([v["K"] for v in views])
    focals = intrinsics[:, [0, 1], [0, 1]]
    report["matches"] = len(ia)

    def unpack(x):
        values = np.vstack([initial[0], x.reshape(-1, 7)])
        return Rotation.from_rotvec(values[:, :3]).as_matrix(), values[:, 3:6], np.exp(values[:, 6])

    def errors(x):
        rotations, translations, scales = unpack(x)
        wa = np.einsum("nij,nj->ni", rotations[ia], left * scales[ia, None]) + translations[ia]
        wb = np.einsum("nij,nj->ni", rotations[ib], right * scales[ib, None]) + translations[ib]
        qa = np.einsum("nji,nj->ni", rotations[ia], wb - translations[ia])
        qb = np.einsum("nji,nj->ni", rotations[ib], wa - translations[ib])
        pixels_a = qa[:, :2] / np.maximum(qa[:, 2:3], 0.1)
        pixels_b = qb[:, :2] / np.maximum(qb[:, 2:3], 0.1)
        pixels_a = pixels_a * focals[ia] + intrinsics[ia, :2, 2]
        pixels_b = pixels_b * focals[ib] + intrinsics[ib, :2, 2]
        return wa - wb, pixels_a - xy_left, pixels_b - xy_right

    def residual(x):
        check()
        xyz, pa, pb = errors(x)
        prior = (x.reshape(-1, 7) - initial[1:]) / np.array([0.15] * 3 + [0.5] * 3 + [0.2])
        return np.r_[np.column_stack([xyz / 0.12, pa / 2, pb / 2]).ravel(), prior.ravel()]

    size = (count - 1) * 7
    sparsity = lil_matrix((len(ia) * 7 + size, size), dtype=int)
    for k, (i, j) in enumerate(zip(ia, ib)):
        for frame in (i, j):
            if frame:
                sparsity[k * 7 : (k + 1) * 7, (frame - 1) * 7 : frame * 7] = 1
    sparsity[len(ia) * 7 :, :] = np.eye(size, dtype=int)
    x0 = initial[1:].ravel()
    radius = np.tile([0.25] * 3 + [0.75] * 3 + [0.25], count - 1)
    before = errors(x0)
    fit = least_squares(
        residual,
        x0,
        jac_sparsity=sparsity.tocsr(),
        bounds=(x0 - radius, x0 + radius),
        loss="soft_l1",
        f_scale=1,
        max_nfev=45,
        ftol=1e-4,
    )
    after = errors(fit.x)
    for label, data in [("before", before), ("after", after)]:
        report[label] = {
            "median_3d_m": float(np.median(np.linalg.norm(data[0], axis=1))),
            "median_reprojection_px": float(
                np.median(np.r_[np.linalg.norm(data[1], axis=1), np.linalg.norm(data[2], axis=1)])
            ),
        }
    report["evaluations"] = fit.nfev
    report["accepted"] = bool(
        report["after"]["median_3d_m"] < report["before"]["median_3d_m"]
        and report["after"]["median_reprojection_px"]
        <= report["before"]["median_reprojection_px"] * 1.05
    )
    rotations, translations, scales = unpack(fit.x if report["accepted"] else x0)
    poses = []
    for rotation, translation in zip(rotations, translations):
        pose = np.eye(4)
        pose[:3, :3], pose[:3, 3] = rotation, translation
        poses.append(pose)
    return poses, scales, report


def project(points, K):
    return points[:, :2] / np.maximum(points[:, 2:3], 0.1) * K[[0, 1], [0, 1]] + K[:2, 2]
