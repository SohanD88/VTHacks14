"""Observed RGB/depth opening outlines, accepted only with repeated view support."""

import cv2
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, Transform
from app.services.fixtures import world_geometry


def detect_portal_edges(rgb, depth):
    h, w = depth.shape
    pad = max(3, round(w * 0.02))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0.8), 50, 120)
    color_distance = cv2.distanceTransform((edges == 0).astype(np.uint8), cv2.DIST_L2, 3)
    horizontal = cv2.HoughLinesP(edges, 1, np.pi / 360, 40, minLineLength=w * 0.4, maxLineGap=12)
    if horizontal is None:
        return []
    jump = np.zeros_like(depth, dtype=np.uint8)
    jump[:, pad:-pad] = (np.abs(depth[:, 2 * pad :] - depth[:, : -2 * pad]) > 0.4) * 255
    lines = cv2.HoughLinesP(
        cv2.Canny(jump, 100, 200), 1, np.pi / 360, 35, minLineLength=h * 0.25, maxLineGap=15
    )
    if lines is None:
        return []
    vertical = []
    for x1, y1, x2, y2 in lines[:, 0]:
        if abs(y2 - y1) < h * 0.25 or abs(x2 - x1) > abs(y2 - y1) * 0.2:
            continue
        slope = (x2 - x1) / (y2 - y1)
        intercept = x1 - slope * y1
        ys = np.linspace(min(y1, y2), max(y1, y2), 30).astype(int)
        xs = np.rint(slope * ys + intercept).astype(int)
        valid = (xs > pad) & (xs < w - pad)
        xs = xs[valid]
        ys = ys[valid]
        if not len(xs):
            continue
        direction = float(np.median(depth[ys, xs + pad] - depth[ys, xs - pad]))
        if abs(direction) < 0.4:
            continue
        vertical.append((slope, intercept, min(y1, y2), max(y1, y2), direction))
    groups = []
    for line in sorted(vertical, key=lambda v: -(v[3] - v[2])):
        match = next(
            (
                g
                for g in groups
                if np.sign(g[0][4]) == np.sign(line[4])
                and abs(g[0][0] - line[0]) < 0.06
                and abs((g[0][0] - line[0]) * h / 2 + g[0][1] - line[1]) < 2 * pad
            ),
            None,
        )
        if match is None:
            groups.append([line])
        else:
            match.append(line)
    vertical = []
    for group in groups:
        ys = np.array([y for line in group for y in line[2:4]])
        xs = np.array([line[0] * y + line[1] for line in group for y in line[2:4]])
        slope, intercept = np.polyfit(ys, xs, 1)
        # A thresholded depth jump is a band. Center it on a nearby color edge
        # instead of fitting whichever band boundary Hough happens to return.
        sample_y = np.linspace(ys.min(), ys.max(), 40).astype(int)
        sign = np.sign(group[0][4])
        shifts = []
        for shift in range(-pad, pad + 1):
            sample_x = np.rint(slope * sample_y + intercept + shift).astype(int)
            valid = (sample_x >= pad) & (sample_x < w - pad)
            if valid.mean() < 0.8:
                continue
            x, y = sample_x[valid], sample_y[valid]
            gap = sign * (depth[y, x + pad] - depth[y, x - pad])
            if np.mean(gap > 0.3) < 0.7:
                continue
            shifts.append((float(np.median(color_distance[y, x])), abs(shift), shift))
        if shifts:
            intercept += min(shifts)[2]
        vertical.append(
            (
                slope,
                intercept,
                int(ys.min()),
                int(ys.max()),
                float(np.median([line[4] for line in group])),
            )
        )
    candidates = []
    for x1, y1, x2, y2 in horizontal[:, 0]:
        if abs(y2 - y1) > abs(x2 - x1) * 0.2:
            continue
        hs = (y2 - y1) / (x2 - x1)
        hi = y1 - hs * x1
        xs = np.linspace(min(x1, x2) + pad, max(x1, x2) - pad, 40).astype(int)
        # Color edges can sit on the outer trim; locate the adjacent depth edge.
        options = []
        for offset in range(-pad * 2, pad * 2 + 1):
            ys = np.rint(hs * xs + hi + offset).astype(int)
            valid = (ys >= pad) & (ys < h - pad)
            if valid.mean() < 0.8:
                continue
            options.append(
                (
                    float(
                        np.median(
                            depth[ys[valid] + pad, xs[valid]] - depth[ys[valid] - pad, xs[valid]]
                        )
                    ),
                    offset,
                    float(np.median(color_distance[ys[valid], xs[valid]])),
                )
            )
        options = [option for option in options if option[0] >= 0.4]
        if not options:
            continue
        base_hi = hi
        for strength, offset, edge_error in options:
            if edge_error > max(3, h * 0.012):
                continue
            hi = base_hi + offset
            for left in vertical:
                for right in vertical:
                    if left[4] < 0 or right[4] > 0:
                        continue
                    yl = (hs * left[1] + hi) / (1 - hs * left[0])
                    xl = left[0] * yl + left[1]
                    yr = (hs * right[1] + hi) / (1 - hs * right[0])
                    xr = right[0] * yr + right[1]
                    if xr - xl < w * 0.35 or not (pad < xl < xr < w - pad):
                        continue
                    top = max(yl, yr)
                    bottom = min(left[3], right[3])
                    if top < pad or top > h * 0.45 or bottom - top < h * 0.35:
                        continue
                    if min(x1, x2) > xl + w * 0.3 or max(x1, x2) < xr - w * 0.3:
                        continue
                    if left[2] > yl + h * 0.2 or right[2] > yr + h * 0.2:
                        continue
                    # Both sides must separate a deeper interior from a near boundary.
                    ys = np.linspace(top + pad * 2, bottom - pad, 40).astype(int)
                    lx = np.rint(left[0] * ys + left[1]).astype(int)
                    rx = np.rint(right[0] * ys + right[1]).astype(int)
                    valid = (lx >= pad) & (rx < w - pad)
                    if valid.mean() < 0.9:
                        continue
                    ys, lx, rx = ys[valid], lx[valid], rx[valid]
                    ldiff = depth[ys, lx + pad] - depth[ys, lx - pad]
                    rdiff = depth[ys, rx - pad] - depth[ys, rx + pad]
                    support = min(float(np.mean(ldiff > 0.3)), float(np.mean(rdiff > 0.3)))
                    if support < 0.7:
                        continue
                    candidates.append(
                        dict(
                            left=left,
                            right=right,
                            top=[[xl, yl], [xr, yr]],
                            bottom=float(bottom),
                            support=support,
                            score=float((xr - xl) * (bottom - top) * support),
                        )
                    )
    unique = []
    seen = set()
    for candidate in sorted(candidates, key=lambda c: -c["score"]):
        key = tuple(np.rint(np.asarray(candidate["top"]).ravel() / 2).astype(int))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= 16:
            break
    return unique


def fit_boundary(candidate, view):
    depth, pose, K = view["depth"], view["pose"], view["K"]
    h, w = depth.shape
    pad = max(3, round(w * 0.02))
    pixels, sides = [], []
    for side, direction in [("left", -1), ("right", 1)]:
        slope, intercept, _, _, _ = candidate[side]
        y = np.linspace(
            max(p[1] for p in candidate["top"]) + 2 * pad, min(h - 1, candidate["bottom"]), 60
        )
        # Sample beyond the depth-transition band, on the observed foreground.
        x = slope * y + intercept + direction * 3 * pad
        pixels.extend(np.column_stack([x, y]))
        sides.extend([side] * len(y))
    top = np.array(candidate["top"])
    x = np.linspace(top[0, 0], top[1, 0], 60)
    y = np.interp(x, top[:, 0], top[:, 1]) - 2 * pad
    pixels.extend(np.column_stack([x, y]))
    sides.extend(["top"] * len(x))
    pixels = np.array(pixels)
    sides = np.array(sides)
    valid = (pixels[:, 0] >= 0) & (pixels[:, 0] < w) & (pixels[:, 1] >= 0) & (pixels[:, 1] < h)
    pixels, sides = pixels[valid], sides[valid]
    if any(np.count_nonzero(sides == side) < 30 for side in ["left", "right", "top"]):
        return None
    z = depth[pixels[:, 1].astype(int), pixels[:, 0].astype(int)]
    rays = np.c_[pixels, np.ones(len(pixels))] @ np.linalg.inv(K).T
    points = (rays * z[:, None]) @ pose[:3, :3].T + pose[:3, 3]
    horizontal = points[:, [0, 2]]
    rng = np.random.default_rng(12)
    best = np.zeros(len(points), bool)
    for _ in range(200):
        a, b = horizontal[rng.choice(len(points), 2, replace=False)]
        delta = b - a
        if np.linalg.norm(delta) < 0.4:
            continue
        normal = np.array([-delta[1], delta[0]]) / np.linalg.norm(delta)
        inside = np.abs((horizontal - a) @ normal) < 0.1
        if inside.sum() > best.sum():
            best = inside
    # Refit consensus before checking support; a noisy two-point hypothesis
    # can underestimate a valid foreground plane's support.
    for _ in range(3):
        if best.sum() < 60:
            return None
        center_xz = horizontal[best].mean(axis=0)
        _, _, axes = np.linalg.svd(horizontal[best] - center_xz, full_matrices=False)
        updated = np.abs((horizontal - center_xz) @ axes[-1]) < 0.1
        if np.array_equal(updated, best):
            break
        best = updated
    if best.mean() < 0.75 or any(
        best[sides == side].mean() < 0.6 for side in ["left", "right", "top"]
    ):
        return None
    center = points[best].mean(0)
    _, _, axes = np.linalg.svd(horizontal[best] - horizontal[best].mean(0), full_matrices=False)
    normal = np.array([axes[-1, 0], 0, axes[-1, 1]])
    rays = np.c_[top, np.ones(2)] @ np.linalg.inv(K).T @ pose[:3, :3].T
    denominator = rays @ normal
    if np.any(np.abs(denominator) < 0.15):
        return None
    distance = ((center - pose[:3, 3]) @ normal) / denominator
    if np.any(distance < 0.2):
        return None
    tops = pose[:3, 3] + rays * distance[:, None]
    if np.ptp(tops[:, 1]) > 0.15:
        return None
    height = float(tops[:, 1].mean())
    tops[:, 1] = height
    width = float(np.linalg.norm(tops[1] - tops[0]))
    if not (0.5 <= width <= 3.5 and 1.4 <= height <= 4.5):
        return None
    corners = np.array([tops[0], tops[1], [tops[1, 0], 0, tops[1, 2]], [tops[0, 0], 0, tops[0, 2]]])
    return dict(
        corners=corners,
        normal=normal,
        center=center,
        points=points[best],
        plane_support=float(best.mean()),
        width=width,
        height=height,
    )


def project_world(points, view):
    camera = (points - view["pose"][:3, 3]) @ view["pose"][:3, :3]
    projected = camera @ view["K"].T
    return projected[:, :2] / np.maximum(projected[:, 2:], 0.01), camera[:, 2]


def opening_support(fit, view, floor_ids):
    """Check both jambs and header against color edges, foreground depth and a gap."""
    uv, z = project_world(fit["corners"], view)
    depth = view["depth"]
    h, w = depth.shape
    pad = max(5, round(w * 0.035))
    if (z < 0.1).any() or not (
        (uv[:2, 0] > pad) & (uv[:2, 0] < w - pad) & (uv[:2, 1] > pad) & (uv[:2, 1] < h * 0.5)
    ).all():
        return None
    gray = cv2.cvtColor(view["rgb"], cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 120)
    edge_distance = cv2.distanceTransform((edges == 0).astype(np.uint8), cv2.DIST_L2, 3)
    boundaries = []
    for start, end, direction in [(uv[0], uv[3], -1), (uv[1], uv[2], 1)]:
        if end[1] <= start[1] + h * 0.35:
            return None
        ys = np.linspace(start[1] + pad * 1.5, min(end[1], h - pad - 1), 40)
        xs = np.interp(ys, [start[1], end[1]], [start[0], end[0]])
        pixels = np.rint(np.c_[xs, ys]).astype(int)
        boundaries.append((pixels, np.array([direction * pad, 0])))
    top = np.rint(np.linspace(uv[0], uv[1], 40)[4:-4]).astype(int)
    boundaries.append((top, np.array([0, -pad])))
    details = []
    for pixels, offset in boundaries:
        outside, inside = pixels + offset, pixels - offset
        valid = (
            (outside[:, 0] >= 0)
            & (outside[:, 0] < w)
            & (outside[:, 1] >= 0)
            & (outside[:, 1] < h)
            & (inside[:, 0] >= 0)
            & (inside[:, 0] < w)
            & (inside[:, 1] >= 0)
            & (inside[:, 1] < h)
        )
        if valid.mean() < 0.8:
            return None
        pixels, outside, inside = pixels[valid], outside[valid], inside[valid]
        rays = (
            np.c_[outside, np.ones(len(outside))]
            @ np.linalg.inv(view["K"]).T
            @ view["pose"][:3, :3].T
        )
        denom = rays @ fit["normal"]
        if np.any(np.abs(denom) < 0.15):
            return None
        predicted = ((fit["center"] - view["pose"][:3, 3]) @ fit["normal"]) / denom
        actual = depth[outside[:, 1], outside[:, 0]]
        gap = depth[inside[:, 1], inside[:, 0]] - actual
        detail = dict(
            edge_error_px=float(np.median(edge_distance[pixels[:, 1], pixels[:, 0]])),
            depth_error_m=float(np.median(abs(actual - predicted))),
            gap_fraction=float(np.mean(gap > 0.35)),
        )
        if (
            detail["edge_error_px"] > max(3, h * 0.012)
            or detail["depth_error_m"] > 0.2
            or detail["gap_fraction"] < 0.7
        ):
            return None
        details.append(detail)
    # A passage needs visible floor behind it; a framed wall decoration is insufficient.
    ys = np.linspace(max(uv[0, 1], uv[1, 1]) + h * 0.2, h - pad - 1, 20)
    samples = []
    for y in ys:
        left = np.interp(y, [uv[0, 1], uv[3, 1]], [uv[0, 0], uv[3, 0]])
        right = np.interp(y, [uv[1, 1], uv[2, 1]], [uv[1, 0], uv[2, 0]])
        samples.extend([[x, y] for x in np.linspace(left + pad, right - pad, 12)])
    samples = np.rint(samples).astype(int)
    valid = (samples[:, 0] >= 0) & (samples[:, 0] < w) & (samples[:, 1] >= 0) & (samples[:, 1] < h)
    samples = samples[valid]
    if len(samples) < 100:
        return None
    floor_fraction = float(
        np.isin(view["semantic"][samples[:, 1], samples[:, 0]], floor_ids).mean()
    )
    if floor_fraction < 0.15:
        return None
    return dict(boundaries=details, floor_fraction=floor_fraction)


def portal_geometry(width, height, stroke=0.045):
    vertices, colors, triangles = [], [], []
    for center, size in [
        ([-width / 2 - stroke / 2, -stroke / 2, 0], [stroke, height, stroke]),
        ([width / 2 + stroke / 2, -stroke / 2, 0], [stroke, height, stroke]),
        ([0, height / 2, 0], [width + 2 * stroke, stroke, stroke]),
    ]:
        x, y, z = np.asarray(size) / 2
        offset = len(vertices)
        vertices.extend(
            (
                np.array(
                    [
                        [-x, -y, -z],
                        [x, -y, -z],
                        [x, y, -z],
                        [-x, y, -z],
                        [-x, -y, z],
                        [x, -y, z],
                        [x, y, z],
                        [-x, y, z],
                    ]
                )
                + center
            ).tolist()
        )
        colors.extend([[1, 0.706, 0.329]] * 8)
        triangles.extend(
            [
                [offset + a, offset + b, offset + c]
                for a, b, c in [
                    (0, 2, 1),
                    (0, 3, 2),
                    (4, 5, 6),
                    (4, 6, 7),
                    (0, 1, 5),
                    (0, 5, 4),
                    (3, 7, 6),
                    (3, 6, 2),
                    (0, 4, 7),
                    (0, 7, 3),
                    (1, 2, 6),
                    (1, 6, 5),
                ]
            ]
        )
    return Geometry(vertices=vertices, colors=colors, triangles=triangles)


def refine_openings(scene, views, floor_ids):
    report = {"openings": []}
    floor = next((o for o in scene.objects if o.kind == "floor"), None)
    if floor is None or not views:
        return scene, report
    for obj in scene.objects:
        if not obj.entrance or obj.transient or len(obj.geometry.vertices) < 35:
            continue
        raw = world_geometry(obj)
        accepted = []
        for view in views:
            if view["frame"] not in obj.source_frames:
                continue
            projected, z = project_world(raw, view)
            if not np.any(z > 0.1):
                continue
            for candidate in detect_portal_edges(view["rgb"], view["depth"]):
                # Tie the proposal to this semantic door evidence, not any rectangle in the view.
                distances = [
                    np.abs(
                        projected[:, 0]
                        - (candidate[side][0] * projected[:, 1] + candidate[side][1])
                    )
                    for side in ["left", "right"]
                ]
                if np.median(np.minimum(*distances)[z > 0.1]) > max(
                    12, view["depth"].shape[1] * 0.06
                ):
                    continue
                fit = fit_boundary(candidate, view)
                if fit is None:
                    continue
                support = {v["frame"]: opening_support(fit, v, floor_ids) for v in views}
                support = {
                    frame: details for frame, details in support.items() if details is not None
                }
                if len(support) < 3:
                    continue
                agreement_error = float(
                    np.mean(
                        [
                            boundary["depth_error_m"] / 0.2
                            + boundary["edge_error_px"] / max(3, view["depth"].shape[0] * 0.012)
                            for details in support.values()
                            for boundary in details["boundaries"]
                        ]
                    )
                )
                accepted.append((len(support), -agreement_error, fit, view["frame"], support))
        if not accepted:
            continue
        _, _, fit, frame, support = max(accepted, key=lambda item: (item[0], item[1]))
        direction = (fit["corners"][1] - fit["corners"][0]) / fit["width"]
        yaw = float(np.arctan2(-direction[2], direction[0]))
        rotation = Rotation.from_euler("y", yaw).as_matrix()
        position = fit["corners"][:2].mean(0)
        position[1] = (fit["height"] + 0.045) / 2
        original = obj.observed_geometry or obj.geometry
        obj.observed_geometry = Geometry(
            vertices=((raw - position) @ rotation).tolist(),
            colors=original.colors,
            triangles=original.triangles,
        )
        obj.geometry = portal_geometry(fit["width"], fit["height"])
        obj.position, obj.rotation, obj.scale = tuple(position), (0, yaw, 0), (1, 1, 1)
        obj.size = (fit["width"] + 0.09, fit["height"] + 0.045, 0.045)
        obj.original_transform = Transform(position=obj.position, rotation=obj.rotation)
        obj.source_frames = sorted(set(obj.source_frames) | set(support))
        obj.supporting_surface = floor.id
        obj.provenance = "primitive_fitted"
        obj.structural, obj.movable = True, False
        obj.method += (
            "; RGB-D opening outline fitted to observed jambs and lintel with multi-view support; "
            "lower edge inferred from observed floor; raw door surface retained"
        )
        # Associate the portal with observed boundary samples, including uncertain wall fragments.
        boundaries = []
        for wall in scene.objects:
            if wall.kind != "wall" and wall.label != "Unresolved wall observations":
                continue
            points = world_geometry(wall)
            if not len(points):
                continue
            distance = float(np.median(cKDTree(points).query(fit["points"])[0]))
            if distance < 0.25:
                boundaries.append((distance, wall.id))
        obj.relationships = [f"boundary:{min(boundaries)[1]}"] if boundaries else []
        report["openings"].append(
            dict(
                object_id=obj.id,
                selected_frame=frame,
                supporting_frames=sorted(support),
                view_support=support,
                plane_center=fit["center"].tolist(),
                plane_normal=fit["normal"].tolist(),
                plane_support=fit["plane_support"],
                corners=fit["corners"].tolist(),
                clear_width=fit["width"],
                clear_height=fit["height"],
                lower_edge="inferred from observed floor",
                boundary_id=min(boundaries)[1] if boundaries else None,
            )
        )
    return scene, report
