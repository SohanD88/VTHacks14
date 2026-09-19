"""Observed-footprint planar structural fitting, with retained raw evidence.

Vertical planes are estimated from wall observations. Grid cells are emitted only
where observations exist; holes and uncaptured boundaries are not closed into a room.
"""

import numpy as np

from app.schemas import Geometry, Transform


def surface_normals(points, faces):
    """Unoriented local normals, robust to inconsistent triangle winding."""
    faces = np.asarray(faces, dtype=int).reshape(-1, 3)
    covariance = np.zeros((len(points), 3, 3))
    if not len(faces):
        return np.zeros_like(points), np.zeros(len(points), bool)
    triangle = points[faces]
    normals = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    area = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(area[:, None], 1e-12)
    moments = normals[:, :, None] * normals[:, None, :] * area[:, None, None]
    for corner in range(3):
        np.add.at(covariance, faces[:, corner], moments)
    values, axes = np.linalg.eigh(covariance)
    normal = axes[:, :, -1]
    # Ambiguous folds and degenerate/isolated vertices cannot support a plane.
    reliable = (values[:, -1] > 1e-10) & (
        values[:, -1] / np.maximum(values.sum(axis=1), 1e-12) > 0.75
    )
    return normal, reliable


def wall_planes(points, normals=None, normal_valid=None):
    rng = np.random.default_rng(22)
    available = np.ones(len(points), bool)
    planes = []
    minimum = max(120, int(len(points) * 0.035))
    horizontal = points[:, [0, 2]]

    def compatible(normal, ids=None):
        if normals is None:
            return np.ones(len(points) if ids is None else len(ids), bool)
        selected = np.arange(len(points)) if ids is None else ids
        return normal_valid[selected] & (
            np.abs(normals[selected][:, [0, 2]] @ normal) > np.cos(np.deg2rad(25))
        )

    for _ in range(8):
        ids = np.flatnonzero(available)
        if len(ids) < minimum:
            break
        sample_ids = rng.choice(ids, min(6000, len(ids)), replace=False)
        sample = horizontal[sample_ids]
        best, score = None, 0
        for _ in range(220):
            a, b = sample[rng.choice(len(sample), 2, replace=False)]
            tangent = b - a
            if np.linalg.norm(tangent) < 0.75:
                continue
            normal = np.array([-tangent[1], tangent[0]]) / np.linalg.norm(tangent)
            offset = a @ normal
            inside = (np.abs(sample @ normal - offset) < 0.18) & compatible(normal, sample_ids)
            if inside.sum() > score:
                best, score = (normal, offset), inside.sum()
        if best is None:
            break
        normal, offset = best
        mask = available & (np.abs(horizontal @ normal - offset) < 0.23) & compatible(normal)
        if mask.sum() < minimum:
            break
        available[mask] = False
        planes.append(np.flatnonzero(mask))
    # Merge nearby duplicate plane estimates using mutual distance at their centroids.
    groups = []
    for ids in planes:
        center = horizontal[ids].mean(axis=0)
        _, _, vectors = np.linalg.svd(horizontal[ids] - center, full_matrices=False)
        normal = vectors[-1]
        match = None
        for group in groups:
            if (
                abs(normal @ group["normal"]) > 0.98
                and abs((center - group["center"]) @ normal) < 0.65
                and abs((center - group["center"]) @ group["normal"]) < 0.65
            ):
                match = group
                break
        if match is None:
            groups.append(dict(ids=ids, center=center, normal=normal))
        else:
            match["ids"] = np.r_[match["ids"], ids]
            values = horizontal[match["ids"]]
            match["center"] = values.mean(axis=0)
            _, _, vectors = np.linalg.svd(values - match["center"], full_matrices=False)
            match["normal"] = vectors[-1]
    return groups


def footprint_mesh(points, colors, normal, origin, spacing=0.09):
    """Each observed plane cell becomes a shared-vertex quad; no hull fills gaps."""
    normal = np.asarray(normal)
    tangent = np.array([normal[2], 0, -normal[0]])
    up = np.array([0.0, 1.0, 0.0])
    uv = np.column_stack(((points - origin) @ tangent, (points - origin) @ up))
    cells, inverse = np.unique(np.floor(uv / spacing).astype(int), axis=0, return_inverse=True)
    count = np.bincount(inverse)
    rgb = np.column_stack([np.bincount(inverse, weights=colors[:, i]) / count for i in range(3)])
    # A cell must contain multiple observations, preventing isolated single-point flakes.
    keep = count >= 2
    cells, rgb = cells[keep], rgb[keep]
    if not len(cells):
        return None
    corners = (cells[:, None, :] + np.array([[0, 0], [1, 0], [1, 1], [0, 1]])).reshape(-1, 2)
    unique, mapping = np.unique(corners, axis=0, return_inverse=True)
    vertices = origin + unique[:, :1] * spacing * tangent + unique[:, 1:] * spacing * up
    repeats = np.repeat(rgb, 4, axis=0)
    counts = np.bincount(mapping)
    vertex_colors = np.column_stack(
        [np.bincount(mapping, weights=repeats[:, i]) / counts for i in range(3)]
    )
    ids = mapping.reshape(-1, 4)
    faces = np.concatenate([ids[:, [0, 1, 2]], ids[:, [0, 2, 3]]])
    return Geometry(
        vertices=np.round(vertices, 4).tolist(),
        colors=np.round(vertex_colors, 3).tolist(),
        triangles=faces.tolist(),
    )


def join_observed_corners(planes, tolerance=0.3, spacing=0.09):
    """Join nearby sampled wall edges only at mutually observed height bins.

    No faces are added and no unseen enclosure is filled. Original observations
    remain in each wall's observed_geometry; this adjusts only the fitted mesh.
    """
    junctions = []
    originals = {wall.id: np.array(wall.geometry.vertices) + wall.position for wall, _, _ in planes}
    adjusted = {key: points.copy() for key, points in originals.items()}
    used = {key: np.zeros(len(points), bool) for key, points in originals.items()}
    candidates = []
    for i, (a, normal_a, center_a) in enumerate(planes):
        for b, normal_b, center_b in planes[:i]:
            # Nearly parallel planes do not define a stable observed corner.
            if abs(normal_a @ normal_b) > np.cos(np.deg2rad(35)):
                continue
            normals = np.array([normal_a[[0, 2]], normal_b[[0, 2]]])
            corner = np.linalg.solve(normals, [normal_a @ center_a, normal_b @ center_b])
            close = []
            for wall in [a, b]:
                points = originals[wall.id]
                distance = np.linalg.norm(points[:, [0, 2]] - corner, axis=1)
                height = np.rint(points[:, 1] / spacing).astype(int)
                tangent = (
                    np.array([-normal_a[2], normal_a[0]])
                    if wall is a
                    else np.array([-normal_b[2], normal_b[0]])
                )
                along = points[:, [0, 2]] @ tangent
                at_corner = corner @ tangent
                boundary = np.zeros(len(points), bool)
                for level in np.unique(height):
                    row = height == level
                    if (
                        min(abs(at_corner - along[row].min()), abs(at_corner - along[row].max()))
                        <= tolerance
                    ):
                        boundary[row] = True
                ids = np.flatnonzero((distance <= tolerance) & boundary)
                close.append(ids)
            if min(map(len, close)) < 8 or any(
                len(ids) > len(originals[wall.id]) / 2 for wall, ids in zip([a, b], close)
            ):
                continue
            bins_a = np.rint(originals[a.id][close[0], 1] / spacing).astype(int)
            bins_b = np.rint(originals[b.id][close[1], 1] / spacing).astype(int)
            common = np.intersect1d(bins_a, bins_b)
            # A few isolated samples do not prove a vertical junction.
            runs = np.split(common, np.flatnonzero(np.diff(common) > 1) + 1)
            supported = [run for run in runs if len(run) >= 4]
            if not supported:
                continue
            common = np.concatenate(supported)
            ids_a, ids_b = close[0][np.isin(bins_a, common)], close[1][np.isin(bins_b, common)]
            distance = max(
                float(np.min(np.linalg.norm(originals[a.id][ids_a][:, [0, 2]] - corner, axis=1))),
                float(np.min(np.linalg.norm(originals[b.id][ids_b][:, [0, 2]] - corner, axis=1))),
            )
            candidates.append((distance, a, b, corner, ids_a, ids_b, common))
    for _, a, b, corner, ids_a, ids_b, common in sorted(candidates, key=lambda c: c[0]):
        moved = []
        for wall, ids in [(a, ids_a), (b, ids_b)]:
            ids = ids[~used[wall.id][ids]]
            if not len(ids):
                break
            moved.append((wall, ids))
        if len(moved) != 2:
            continue
        maximum = 0.0
        for wall, ids in moved:
            points = adjusted[wall.id]
            points[np.ix_(ids, [0, 2])] = corner
            points[ids, 1] = np.rint(points[ids, 1] / spacing) * spacing
            maximum = max(
                maximum, float(np.linalg.norm(points[ids] - originals[wall.id][ids], axis=1).max())
            )
            used[wall.id][ids] = True
            other = b if wall is a else a
            wall.relationships = sorted(set(wall.relationships + [f"adjacent:{other.id}"]))
        junctions.append(
            dict(
                walls=[a.id, b.id],
                intersection_xz=corner.tolist(),
                supported_height_bins=common.tolist(),
                grid_spacing=spacing,
                adjusted_vertices=sum(len(ids) for _, ids in moved),
                maximum_displacement=round(maximum, 4),
            )
        )
    for wall, _, _ in planes:
        if not used[wall.id].any():
            continue
        points = adjusted[wall.id]
        faces = np.asarray(wall.geometry.triangles, dtype=int).reshape(-1, 3)
        # Collapsing the corner strip can degenerate quads; remove zero-area faces.
        triangles = points[faces]
        area = np.linalg.norm(
            np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
        )
        wall.geometry = Geometry(
            vertices=np.round(points - wall.position, 4).tolist(),
            colors=wall.geometry.colors,
            triangles=faces[area > 1e-8].tolist(),
        )
        wall.size = tuple(np.maximum(0.025, np.ptp(points, axis=0)))
        wall.method += "; nearby corner edges aligned only at mutually observed heights"
    return junctions


def refine_structures(scene, wall_observations=()):
    result, fitted_planes = [], []
    report = {
        "wall_planes": 0,
        "wall_vertices": 0,
        "supported_wall_vertices": 0,
        "aligned_insets": 0,
        "plane_orientation_support": [],
    }
    camera = np.mean(scene.camera_path, axis=0) if scene.camera_path else np.zeros(3)
    for obj in scene.objects:
        if obj.kind != "wall" or len(obj.geometry.vertices) < 300:
            result.append(obj)
            continue
        points = np.asarray(obj.geometry.vertices) + obj.position
        colors = np.asarray(obj.geometry.colors)
        normals, normal_valid = surface_normals(points, obj.geometry.triangles)
        groups = (
            wall_planes(points, normals, normal_valid)
            if obj.geometry.triangles
            else wall_planes(points)
        )
        if not groups:
            result.append(obj)
            continue
        report["wall_vertices"] += len(points)
        covered = np.zeros(len(points), bool)
        for i, group in enumerate(groups):
            ids = group["ids"]
            patch = points[ids]
            center = np.median(patch, axis=0)
            normal = np.array([group["normal"][0], 0, group["normal"][1]])
            if np.dot(camera - center, normal) < 0:
                normal = -normal
            center[[0, 2]] = group["center"]
            mesh = footprint_mesh(patch, colors[ids], normal, center)
            if mesh is None:
                continue
            covered[ids] = True
            vertices = np.asarray(mesh.vertices)
            mesh.vertices = [tuple(p) for p in np.round(vertices - center, 4).tolist()]
            size = np.maximum(0.025, np.ptp(vertices, axis=0))
            remap = np.full(len(points), -1, int)
            remap[ids] = np.arange(len(ids))
            faces = np.asarray(obj.geometry.triangles, dtype=int).reshape(-1, 3)
            faces = faces[(remap[faces] >= 0).all(axis=1)]
            raw = Geometry(
                vertices=(patch - center).tolist(),
                colors=colors[ids].tolist(),
                triangles=remap[faces].tolist(),
            )
            wall = obj.model_copy(deep=True)
            wall.id = obj.id if i == 0 else f"{obj.id}-plane-{i + 1}"
            wall.label = f"Observed wall plane {i + 1}"
            wall.position, wall.size = tuple(center), tuple(size)
            wall.geometry, wall.observed_geometry = mesh, raw
            wall.original_transform = Transform(position=wall.position)
            wall.provenance = "primitive_fitted"
            wall.method = (
                "Robust vertical plane fit to observed wall points"
                + (" with local surface orientation" if obj.geometry.triangles else "")
                + "; observed-cell mesh, no unseen enclosure"
            )
            if wall_observations:
                low, high = patch.min(axis=0) - 0.2, patch.max(axis=0) + 0.2
                wall.source_frames = sorted(
                    {
                        frame
                        for frame, samples in wall_observations
                        if np.count_nonzero(
                            (np.abs((samples - center) @ normal) < 0.3)
                            & ((samples >= low) & (samples <= high)).all(axis=1)
                        )
                        >= 18
                    }
                )
            report["plane_orientation_support"].append(
                dict(
                    object_id=wall.id,
                    normal=normal.tolist(),
                    vertices=len(ids),
                    locally_oriented_vertices=int(normal_valid[ids].sum()),
                    median_normal_agreement=float(np.median(np.abs(normals[ids] @ normal)))
                    if normal_valid[ids].any()
                    else None,
                )
            )
            result.append(wall)
            fitted_planes.append((wall, normal, center))
        report["supported_wall_vertices"] += int(covered.sum())
        # Preserve unsupported observations explicitly as uncertain structural geometry.
        if (~covered).sum() >= 35:
            ids = np.flatnonzero(~covered)
            remap = np.full(len(points), -1, int)
            remap[ids] = np.arange(len(ids))
            faces = np.asarray(obj.geometry.triangles, dtype=int).reshape(-1, 3)
            faces = faces[(remap[faces] >= 0).all(axis=1)]
            candidate = obj.model_copy(deep=True)
            candidate.id += "-uncertain"
            candidate.kind, candidate.label = "unknown", "Unresolved wall observations"
            candidate.method = (
                "Wall observations not supported by the fitted planes; retained for review"
            )
            candidate.geometry = Geometry(
                vertices=(points[ids] - obj.position).tolist(),
                colors=colors[ids].tolist(),
                triangles=remap[faces].tolist(),
            )
            result.append(candidate)
    report["corner_junctions"] = join_observed_corners(fitted_planes)
    # Align only nearby wall-associated surfaces, retaining their complete raw geometry.
    for obj in result:
        if obj.entrance and fitted_planes:
            boundary = min(
                fitted_planes, key=lambda p: abs(np.dot(np.asarray(obj.position) - p[2], p[1]))
            )
            obj.relationships = [f"boundary:{boundary[0].id}"]
        if obj.kind not in {"windowpane", "screen", "curtain", "painting"} or not fitted_planes:
            continue
        points = np.asarray(obj.geometry.vertices) + obj.position
        wall, normal, center = min(
            fitted_planes, key=lambda p: abs(np.dot(np.asarray(obj.position) - p[2], p[1]))
        )
        distances = (points - center) @ normal
        if np.median(np.abs(distances)) > 0.8:
            continue
        # Keep the same observed footprint; a tiny inset avoids z-fighting with the wall.
        refined = points - (distances[:, None] - 0.015) * normal
        new_center = np.median(refined, axis=0)
        obj.observed_geometry = Geometry(
            vertices=(points - new_center).tolist(),
            colors=obj.geometry.colors,
            triangles=obj.geometry.triangles,
        )
        obj.geometry = Geometry(
            vertices=(refined - new_center).tolist(),
            colors=obj.geometry.colors,
            triangles=obj.geometry.triangles,
        )
        obj.position = tuple(new_center)
        obj.size = tuple(np.maximum(0.025, np.ptp(refined, axis=0)))
        obj.original_transform = Transform(position=obj.position)
        obj.provenance = "primitive_fitted"
        obj.method = (
            "Observed wall-associated surface projected to nearby fitted boundary; "
            "raw evidence retained"
        )
        obj.relationships = [f"boundary:{wall.id}"]
        report["aligned_insets"] += 1
    report["wall_planes"] = len(fitted_planes)
    scene.objects = result
    return scene, report
