"""Observed ceiling support for small light surfaces; retain unfitted evidence."""

import cv2
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, Transform


def world_geometry(obj):
    geometry = obj.observed_geometry or obj.geometry
    rotation = Rotation.from_euler("xyz", obj.rotation).as_matrix()
    return np.asarray(geometry.vertices) * obj.scale @ rotation.T + obj.position


def ceiling_plane(points):
    if len(points) < 100:
        return None
    sample = points[np.linspace(0, len(points) - 1, min(6000, len(points)), dtype=int)]
    rng = np.random.default_rng(42)
    best = np.zeros(len(sample), bool)
    for _ in range(250):
        a, b, c = sample[rng.choice(len(sample), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length < 1e-8:
            continue
        normal /= length
        if abs(normal[1]) < 0.75:
            continue
        inside = np.abs((sample - a) @ normal) < 0.1
        if inside.sum() > best.sum():
            best = inside
    if best.mean() < 0.6:
        return None
    center = sample[best].mean(axis=0)
    _, singular, axes = np.linalg.svd(sample[best] - center, full_matrices=False)
    normal = axes[-1]
    if normal[1] < 0:
        normal = -normal
    if normal[1] < 0.75 or singular[1] / np.sqrt(best.sum()) < 0.3:
        return None
    support = np.abs((points - center) @ normal) < 0.1
    if support.mean() < 0.6:
        return None
    return center, normal, support


def mask_support(points, view):
    pose = view["pose"]
    camera = (points - pose[:3, 3]) @ pose[:3, :3]
    projected = camera @ view["K"].T
    pixels = np.rint(projected[:, :2] / np.maximum(projected[:, 2:], 0.01) / view["step"]).astype(
        int
    )
    mask = view["mask"]
    valid = (
        (camera[:, 2] > 0.1)
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] < mask.shape[1])
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < mask.shape[0])
    )
    hits = np.zeros(len(points), bool)
    hits[valid] = mask[pixels[valid, 1], pixels[valid, 0]]
    if valid.sum() < 3:
        return 0.0
    # Require coverage as well as inclusion: a tiny partial patch must not win
    # merely because all its vertices fall inside a much larger target mask.
    silhouette = np.zeros(mask.shape, dtype=np.uint8)
    cv2.fillConvexPoly(silhouette, cv2.convexHull(pixels[valid].astype(np.int32)), 1)
    intersection = (silhouette.astype(bool) & mask).sum()
    return float(
        min(hits.mean(), intersection / max(1, mask.sum()), intersection / max(1, silhouette.sum()))
    )


def refine_ceiling_lights(scene, observations):
    report = {"ceiling_planes": [], "fixtures": [], "merges": []}
    planes = []
    for ceiling in scene.objects:
        if ceiling.kind != "ceiling" or ceiling.confidence < 0.6 or len(ceiling.source_frames) < 3:
            continue
        points = world_geometry(ceiling)
        fit = ceiling_plane(points)
        if fit is None:
            continue
        center, normal, support = fit
        planes.append((ceiling.id, center, normal, cKDTree(points[support])))
        report["ceiling_planes"].append(
            dict(
                object_id=ceiling.id,
                center=center.tolist(),
                normal=normal.tolist(),
                supported_fraction=float(support.mean()),
            )
        )
    for obj in scene.objects:
        views = observations.get(obj.id, [])
        if obj.kind != "light" or obj.transient or obj.confidence < 0.6 or len(views) < 3:
            continue
        raw = world_geometry(obj)
        candidates = []
        for ceiling_id, origin, normal, tree in planes:
            distances = np.abs((raw - origin) @ normal)
            if np.median(distances) > 0.2 or np.percentile(distances, 90) > 0.25:
                continue
            for view in views:
                points, camera = view["points"], view["pose"][:3, 3]
                rays = points - camera
                denominator = rays @ normal
                if np.any(
                    np.abs(denominator) / np.maximum(np.linalg.norm(rays, axis=1), 1e-8) < 0.1
                ):
                    continue
                scale = ((origin - camera) @ normal) / denominator
                if np.any((scale < 0.65) | (scale > 1.5)):
                    continue
                fitted = camera + rays * scale[:, None]
                if np.percentile(tree.query(fitted)[0], 90) > 0.35:
                    continue  # Do not extend the ceiling into unobserved space.
                supports = {v["frame"]: mask_support(fitted, v) for v in views}
                supported = [frame for frame, fraction in supports.items() if fraction >= 0.55]
                if len(supported) < 3 or len(supported) < len(supports) * 0.5:
                    continue
                candidates.append(
                    (
                        len(supported),
                        len(points) * view["score"],
                        ceiling_id,
                        fitted,
                        view,
                        supports,
                    )
                )
        if not candidates:
            continue
        _, _, ceiling_id, fitted, view, supports = max(candidates, key=lambda c: (c[1], c[0]))
        center = np.median(fitted, axis=0)
        original = obj.observed_geometry or obj.geometry
        obj.observed_geometry = Geometry(
            vertices=(raw - center).tolist(),
            colors=original.colors,
            triangles=original.triangles,
        )
        obj.geometry = Geometry(
            vertices=(fitted - center).tolist(),
            colors=view["colors"].tolist(),
            triangles=view["triangles"].tolist(),
        )
        obj.position, obj.rotation, obj.scale = tuple(center), (0, 0, 0), (1, 1, 1)
        obj.size = tuple(np.maximum(np.ptp(fitted, axis=0), 0.025))
        obj.original_transform = Transform(position=obj.position)
        obj.supporting_surface = ceiling_id
        obj.structural, obj.movable = True, False
        obj.provenance = "primitive_fitted"
        obj.label = f"Ceiling light candidate {obj.id}"
        obj.method += (
            "; observed ceiling-plane fit with multi-view mask support; raw surface retained"
        )
        report["fixtures"].append(
            dict(
                object_id=obj.id,
                ceiling_id=ceiling_id,
                selected_frame=view["frame"],
                supporting_frames=[f for f, fraction in supports.items() if fraction >= 0.55],
                mask_support={str(f): fraction for f, fraction in supports.items()},
                original_extent=np.ptp(raw, axis=0).tolist(),
                fitted_extent=np.ptp(fitted, axis=0).tolist(),
            )
        )
    merge_fitted_lights(scene, observations, report)
    return scene, report


def merge_fitted_lights(scene, observations, report):
    """Merge only disjoint, co-located fits with reciprocal source-mask evidence."""
    details = {entry["object_id"]: entry for entry in report["fixtures"]}
    fitted = [obj for obj in scene.objects if obj.id in details]
    removed = set()
    for index, target in enumerate(fitted):
        if target.id in removed:
            continue
        for other in fitted[index + 1 :]:
            if other.id in removed or set(target.source_frames) & set(other.source_frames):
                continue
            if target.supporting_surface != other.supporting_surface:
                continue
            if np.linalg.norm(np.asarray(target.position) - other.position) > 0.2:
                continue
            a = np.asarray(target.geometry.vertices) + target.position
            b = np.asarray(other.geometry.vertices) + other.position
            reciprocal = [
                float(np.median([mask_support(a, view) for view in observations[other.id]])),
                float(np.median([mask_support(b, view) for view in observations[target.id]])),
            ]
            if min(reciprocal) < 0.55:
                continue
            first, second = target.observed_geometry, other.observed_geometry
            raw = np.vstack([world_geometry(target), world_geometry(other)])
            offset = len(first.vertices)
            target.observed_geometry = Geometry(
                vertices=(raw - target.position).tolist(),
                colors=first.colors + second.colors,
                triangles=first.triangles
                + [tuple(i + offset for i in face) for face in second.triangles],
            )
            target.source_frames = sorted(set(target.source_frames + other.source_frames))
            observations[target.id] = observations[target.id] + observations[other.id]
            target.confidence = round(
                float(np.mean([v["score"] for v in observations[target.id]])), 4
            )
            support = {str(v["frame"]): mask_support(a, v) for v in observations[target.id]}
            details[target.id].update(
                supporting_frames=[int(f) for f, fraction in support.items() if fraction >= 0.55],
                mask_support=support,
                original_extent=np.ptp(raw, axis=0).tolist(),
            )
            report["merges"].append(
                dict(
                    source_id=other.id,
                    target_id=target.id,
                    reciprocal_mask_support=reciprocal,
                    source_frames=target.source_frames,
                )
            )
            removed.add(other.id)
    scene.objects = [obj for obj in scene.objects if obj.id not in removed]
    report["fixtures"] = [
        entry for entry in report["fixtures"] if entry["object_id"] not in removed
    ]
