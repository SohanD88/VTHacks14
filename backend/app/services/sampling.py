"""Local pixel sampling for observed surfaces smaller than the coarse fusion grid."""

import cv2
import numpy as np


def region_triangles(selected, points):
    """Triangulate observed neighboring pixels without spanning holes or depth jumps."""
    yy, xx = np.nonzero(selected)
    mapping = np.full(selected.shape, -1, dtype=int)
    mapping[selected] = np.arange(len(points))
    grid = mapping[yy.min() : yy.max() + 1, xx.min() : xx.max() + 1]
    a, b, c, d = grid[:-1, :-1], grid[:-1, 1:], grid[1:, :-1], grid[1:, 1:]
    faces = np.concatenate(
        (np.stack((a, c, b), axis=-1).reshape(-1, 3), np.stack((b, c, d), axis=-1).reshape(-1, 3))
    )
    faces = faces[(faces >= 0).all(axis=1)]
    if len(faces):
        corners = points[faces]
        edges = np.linalg.norm(corners - np.roll(corners, 1, axis=1), axis=2)
        faces = faces[edges.max(axis=1) < 0.35]
    return faces


def small_observations(rgb, depth, semantic, confidence, pose, K, labels, step, excluded):
    """Rescue small semantic components that cannot meet coarse sampling's 18-point gate.

    Keep the existing per-pixel confidence gate. Final semantic reliability still
    requires repeated observations. Bound region size/count to preserve memory.
    """
    candidates = []
    for class_id in np.unique(semantic):
        name = labels[int(class_id)].split(",")[0].strip()
        if name in excluded:
            continue
        mask = (semantic == class_id) & (confidence > 0.32)
        count, components, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        for component in range(1, count):
            area = int(stats[component, cv2.CC_STAT_AREA])
            if not 50 <= area <= 2000:
                continue
            selected = components == component
            if selected[::step, ::step].sum() >= 18:
                continue
            score = float(confidence[selected].mean())
            candidates.append((score * np.sqrt(area), name, np.flatnonzero(selected), score))
    observations = []
    for _, name, indices, score in sorted(candidates, key=lambda c: -c[0])[:16]:
        selected = np.zeros(depth.shape, dtype=bool)
        selected.ravel()[indices] = True
        yy, xx = np.nonzero(selected)
        z = depth[selected]
        camera = np.column_stack(((xx - K[0, 2]) * z / K[0, 0], (yy - K[1, 2]) * z / K[1, 1], z))
        points = camera @ pose[:3, :3].T + pose[:3, 3]
        lo, hi = np.percentile(points, [2, 98], axis=0)
        if np.max(hi - lo) > 20:
            continue
        observations.append(
            dict(
                kind=name,
                instance=False,
                fine_surface=True,
                centroid=np.median(points, axis=0),
                pts=points,
                lo=lo,
                hi=hi,
                selected=selected,
                confidence=score,
                colors=rgb[selected] / 255,
                triangles=region_triangles(selected, points),
                width=float(np.ptp(xx) * np.median(z) / K[0, 0]),
                step=1,
            )
        )
    return observations
