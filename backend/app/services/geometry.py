"""RGB-D pose tracking and observed-surface meshing; no invented room envelope."""

import cv2
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.assets import furniture
from app.services.sampling import region_triangles, small_observations
from app.services.tracking import associate_instances, consolidate_instances

STRUCTURAL = {
    "wall",
    "floor",
    "ceiling",
    "windowpane",
    "door",
    "column",
    "stairs",
    "stairway",
    "step",
    "beam",
    "railing",
    "fireplace",
}
TRANSIENT = {"person", "animal", "car", "bicycle", "bus", "truck"}
OPENINGS = {"door", "windowpane", "screen door"}


def intrinsics(rgb):
    h, w = rgb.shape[:2]
    return np.array(
        [[max(h, w) * 0.85, 0, w / 2], [0, max(h, w) * 0.85, h / 2], [0, 0, 1.0]], dtype=np.float64
    )


def unproject(pixels, depth, K):
    z = depth[
        np.clip(pixels[:, 1].astype(int), 0, depth.shape[0] - 1),
        np.clip(pixels[:, 0].astype(int), 0, depth.shape[1] - 1),
    ]
    return np.column_stack(
        ((pixels[:, 0] - K[0, 2]) * z / K[0, 0], (pixels[:, 1] - K[1, 2]) * z / K[1, 1], z)
    )


class Tracker:
    def __init__(self):
        self.sift = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.01, edgeThreshold=20)
        self.references = []
        self.failures = 0
        self.records = []
        self.views = []
        self.failed_views = []

    def track(self, rgb, depth, labels, dynamic_ids, frame):
        K = intrinsics(rgb)
        mask = (~np.isin(labels, dynamic_ids)).astype(np.uint8) * 255
        keypoints, descriptors = self.sift.detectAndCompute(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), mask
        )
        pixels = np.array([p.pt for p in keypoints], dtype=np.float32)
        record = {"frame": frame, "features": len(pixels), "success": False, "inliers": 0}
        if descriptors is None or len(pixels) < 16:
            self.failures += 1
            self.records.append(record)
            return None
        if not self.references:
            pose = np.eye(4)
            record.update(success=True, method="origin", inliers=len(pixels))
        else:
            pose = None
            # Relocalize against several recent accepted observations after tracking loss.
            for previous in self.references[-4:][::-1]:
                old_desc, old_pixels, old_depth, old_pose, old_K = previous
                pairs = cv2.BFMatcher().knnMatch(old_desc, descriptors, k=2)
                matches = [
                    a
                    for pair in pairs
                    if len(pair) == 2
                    for a, b in [pair]
                    if a.distance < 0.8 * b.distance
                ]
                if len(matches) < 14:
                    continue
                p0 = old_pixels[[m.queryIdx for m in matches]]
                p1 = pixels[[m.trainIdx for m in matches]]
                xyz = unproject(p0, old_depth, old_K) @ old_pose[:3, :3].T + old_pose[:3, 3]
                ok, rvec, tvec, inliers = cv2.solvePnPRansac(
                    xyz,
                    p1,
                    K,
                    None,
                    iterationsCount=180,
                    reprojectionError=3.5,
                    confidence=0.999,
                    flags=cv2.SOLVEPNP_EPNP,
                )
                if (
                    not ok
                    or inliers is None
                    or len(inliers) < 14
                    or len(inliers) / len(matches) < 0.28
                ):
                    continue
                ids = inliers[:, 0]
                rvec, tvec = cv2.solvePnPRefineLM(xyz[ids], p1[ids], K, None, rvec, tvec)
                R = cv2.Rodrigues(rvec)[0]
                candidate = np.eye(4)
                candidate[:3, :3] = R.T
                candidate[:3, 3] = -R.T @ tvec[:, 0]
                distance = np.linalg.norm(candidate[:3, 3] - old_pose[:3, 3])
                angle = Rotation.from_matrix(candidate[:3, :3].T @ old_pose[:3, :3]).magnitude()
                if distance > 2.5 or angle > 1.2:
                    continue
                reproj = cv2.projectPoints(xyz[ids], rvec, tvec, K, None)[0][:, 0]
                record.update(
                    success=True,
                    inliers=len(inliers),
                    matches=len(matches),
                    reprojection_px=float(np.linalg.norm(reproj - p1[ids], axis=1).mean()),
                    translation=float(distance),
                    rotation_radians=float(angle),
                )
                # Align monocular depth scale to multiview geometric evidence.
                camera_xyz = xyz[ids] @ R.T + tvec[:, 0]
                predicted = unproject(p1[ids], depth, K)[:, 2]
                ratio = np.median(camera_xyz[:, 2] / np.maximum(predicted, 0.1))
                if 0.65 < ratio < 1.5:
                    depth *= float(ratio)
                    record["depth_scale_alignment"] = float(ratio)
                pose = candidate
                break
        if pose is None:
            self.failures += 1
            self.failed_views.append(
                dict(
                    pixels=pixels,
                    descriptors=descriptors,
                    xyz=unproject(pixels, depth, K),
                    K=K,
                    frame=frame,
                )
            )
            self.records.append(record)
            return None
        self.references.append((descriptors, pixels, depth, pose, K))
        self.references = self.references[-8:]
        self.views.append(
            dict(
                pose=pose.copy(),
                pixels=pixels,
                descriptors=descriptors,
                xyz=unproject(pixels, depth, K),
                K=K,
                frame=frame,
            )
        )
        record["camera_to_initial_camera"] = pose.tolist()
        self.records.append(record)
        return pose


class Fusion:
    def __init__(self, labels, step=5):
        self.labels = labels
        self.step = step
        self.groups = []
        self.camera = []
        self.frames = []
        self.merged = 0
        self.features = {}
        self.opening_views = []

    def add(self, rgb, depth, semantic, confidence, pose, frame, detections=(), features=None):
        if features is not None:
            self.features[frame] = features
        h, w = depth.shape
        step = self.step
        K = intrinsics(rgb)
        self.opening_views.append(
            dict(rgb=rgb, depth=depth, semantic=semantic, pose=pose.copy(), K=K, frame=frame)
        )
        yy, xx = np.mgrid[0:h:step, 0:w:step]
        pixels = np.column_stack((xx.ravel(), yy.ravel()))
        points = unproject(pixels, depth, K) @ pose[:3, :3].T + pose[:3, 3]
        colors = rgb[yy, xx].reshape(-1, 3) / 255
        sem = semantic[yy, xx]
        conf = confidence[yy, xx]
        self.camera.append(pose[:3, 3].copy())
        self.frames.append(frame)
        # Instance boxes separate chairs/couches/tables; semantic masks keep only surfaces.
        assigned = np.zeros(sem.shape, dtype=bool)
        regions = []
        aliases = {
            "couch": {"sofa", "armchair", "ottoman", "bed"},
            "chair": {"chair", "armchair", "swivel chair", "seat", "stool"},
            "dining table": {"table", "coffee table", "desk"},
        }
        canonical = {"couch": "sofa", "dining table": "table"}
        for detection in sorted(detections, key=lambda d: -d["confidence"]):
            label = detection["label"]
            if label not in aliases:
                continue
            classes = [
                k for k, v in self.labels.items() if v.split(",")[0].strip() in aliases[label]
            ]
            left, top, right, bottom = detection["box"]
            region = (
                np.isin(sem, classes)
                & (xx >= left * w)
                & (xx <= right * w)
                & (yy >= top * h)
                & (yy <= bottom * h)
                & ~assigned
            )
            if region.sum() < 12:
                continue
            assigned |= region
            regions.append((canonical.get(label, label), region, detection["confidence"], True))
        for class_id in np.unique(sem):
            name = self.labels[int(class_id)].split(",")[0].strip()
            if name in TRANSIENT:
                continue
            mask = (sem == class_id) & (conf > 0.32) & ~assigned
            count, components = cv2.connectedComponents(mask.astype(np.uint8))
            for component in range(1, count):
                selected = components == component
                if selected.sum() >= 18:
                    regions.append((name, selected, float(conf[selected].mean()), False))
        observations = []
        for name, selected, mean_conf, instance in regions:
            indices = np.flatnonzero(selected)
            pts = points[indices]
            lo, hi = np.percentile(pts, [2, 98], axis=0)
            if np.max(hi - lo) <= 20:
                observations.append(
                    dict(
                        kind=name,
                        instance=instance,
                        centroid=np.median(pts, axis=0),
                        pts=pts,
                        colors=colors[indices],
                        triangles=region_triangles(selected, pts),
                        width=float(
                            np.ptp(pixels[indices, 0])
                            * np.median(depth[yy, xx][selected])
                            / K[0, 0]
                        ),
                        step=step,
                        lo=lo,
                        hi=hi,
                        selected=selected,
                        confidence=mean_conf,
                    )
                )
        # Keep furniture instance handling and broad structures on the original
        # grid; sample overlooked small persistent surfaces at pixel resolution.
        excluded = STRUCTURAL | TRANSIENT | set().union(*aliases.values())
        observations.extend(
            small_observations(
                rgb, depth, semantic, confidence, pose, K, self.labels, step, excluded
            )
        )
        matches = associate_instances(observations, self.groups, dict(pose=pose, K=K))
        for observation_id, observation in enumerate(observations):
            name, instance = observation["kind"], observation["instance"]
            selected, mean_conf = observation["selected"], observation["confidence"]
            pts = observation["pts"]
            lo, hi = observation["lo"], observation["hi"]
            group = self.groups[matches[observation_id]] if observation_id in matches else None
            for candidate in self.groups if not instance else ():
                if candidate["kind"] != name or candidate["instance"]:
                    continue
                if frame in candidate["frames"] and (
                    candidate.get("fine_surface") or observation.get("fine_surface")
                ):
                    continue  # Distinct small surfaces seen together cannot share an identity.
                if name in {"wall", "floor", "ceiling"}:
                    group = candidate
                    break
                overlap = np.maximum(
                    0, np.minimum(hi, candidate["hi"]) - np.maximum(lo, candidate["lo"])
                )
                smaller = np.maximum(0.01, np.minimum(hi - lo, candidate["hi"] - candidate["lo"]))
                if (
                    np.prod(overlap / smaller) > 0.08
                    or np.linalg.norm((hi + lo - candidate["hi"] - candidate["lo"]) / 2) < 0.35
                ):
                    group = candidate
                    break
            if group is None:
                group = dict(
                    kind=name,
                    instance=instance,
                    centroid=np.median(pts, axis=0),
                    widths=[],
                    views=[],
                    lo=lo,
                    hi=hi,
                    vertices=[],
                    colors=[],
                    triangles=[],
                    scores=[],
                    frames=[],
                )
                self.groups.append(group)
            else:
                self.merged += 1
                group["lo"] = np.minimum(group["lo"], lo)
                group["hi"] = np.maximum(group["hi"], hi)
            group["centroid"] = group["centroid"] * 0.65 + np.median(pts, axis=0) * 0.35
            offset = sum(len(p) for p in group["vertices"])
            group["fine_surface"] = group.get("fine_surface", False) or observation.get(
                "fine_surface", False
            )
            group["widths"].append(observation["width"])
            group["vertices"].append(pts)
            group["colors"].append(observation["colors"])
            group["triangles"].append(observation["triangles"] + offset)
            group["scores"].append(mean_conf)
            group["frames"].append(frame)
            group["views"].append(
                dict(
                    pose=pose.copy(),
                    K=K,
                    mask=selected.copy(),
                    step=observation["step"],
                    frame=frame,
                )
            )

    def finish(self, check=lambda: None):
        self.groups, self.instance_report = consolidate_instances(self.groups)
        self.merged += len(self.instance_report)
        from app.services.motion import MotionAnalyzer

        analyzer = MotionAnalyzer(self.features)
        self.motion_report = []
        for group in self.groups:
            check()
            motion = (
                analyzer.assess(group["views"])
                if group["kind"] not in STRUCTURAL
                else dict(status="structural", pairs=[])
            )
            group["transient"] = motion["status"] == "moving_candidate"
            group["motion"] = dict(
                kind=group["kind"],
                source_frames=sorted(set(group["frames"])),
                object_ids=[],
                **motion,
            )
            self.motion_report.append(group["motion"])
        # Estimate up from actual segmented floor points, robustly fit a floor plane.
        floor_points = [np.concatenate(g["vertices"]) for g in self.groups if g["kind"] == "floor"]
        normal = np.array([0.0, -1.0, 0.0])
        floor_offset = 0.0
        floor_found = False
        if floor_points:
            pts = np.concatenate(floor_points)[::3]
            rng = np.random.default_rng(42)
            best = np.zeros(len(pts), bool)
            for _ in range(180):
                if len(pts) < 3:
                    break
                a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
                n = np.cross(b - a, c - a)
                norm = np.linalg.norm(n)
                if norm < 1e-6:
                    continue
                n /= norm
                if abs(n[1]) < 0.6:
                    continue
                inside = np.abs((pts - a) @ n) < 0.09
                if inside.sum() > best.sum():
                    best = inside
            if best.sum() > 30:
                center = pts[best].mean(axis=0)
                _, _, vh = np.linalg.svd(pts[best] - center, full_matrices=False)
                normal = vh[-1]
                if normal[1] > 0:
                    normal = -normal
                floor_offset = float(center @ normal)
                floor_found = True
        up = np.array([0.0, 1.0, 0.0])
        axis = np.cross(normal, up)
        cos = np.dot(normal, up)
        if np.linalg.norm(axis) < 1e-8:
            R = np.diag([1.0, -1.0, -1.0]) if cos < 0 else np.eye(3)
        else:
            R = Rotation.from_rotvec(
                axis / np.linalg.norm(axis) * np.arccos(np.clip(cos, -1, 1))
            ).as_matrix()

        def orient(p):
            q = np.asarray(p) @ R.T
            q[:, 1] -= floor_offset
            return q

        objects = []
        fit_widths = {}
        fixture_observations = {}
        for g in self.groups:
            if g["instance"] or g["transient"]:
                # Depth drift can smear a tracked object's silhouette. Preserve its best
                # observed view; retain every supporting frame as track evidence.
                best = max(
                    range(len(g["vertices"])), key=lambda i: len(g["vertices"][i]) * g["scores"][i]
                )
                vertices = orient(g["vertices"][best])
                colors = g["colors"][best]
                offset = sum(len(p) for p in g["vertices"][:best])
                faces = g["triangles"][best] - offset
                observation_ids = None  # Instance/motion tracks retain all matched-view evidence.
            else:
                vertices = orient(np.concatenate(g["vertices"]))
                colors = np.concatenate(g["colors"])
                faces = np.concatenate(g["triangles"])
                observation_ids = np.repeat(
                    np.arange(len(g["vertices"])), [len(points) for points in g["vertices"]]
                )
            if g["kind"] == "floor" and floor_found:
                # Refine only observations close to the measured dominant plane.
                # Preserve their footprint and topology: do not fill unseen floor,
                # flatten stairs, or move evidence of another floor elevation.
                vertices = stabilize_floor(vertices)
            vertices, colors, faces, voxel_ids = voxel_mesh(
                vertices,
                colors,
                faces,
                spacing=0.015 if g.get("fine_surface") else 0.035,
                return_inverse=True,
            )
            kind = g["kind"]
            # Separate disconnected objects that briefly shared a 2D semantic region.
            components = [np.arange(len(vertices))]
            if kind not in STRUCTURAL and not g["instance"] and len(vertices) > 30:
                pairs = cKDTree(vertices).query_pairs(0.18, output_type="ndarray")
                graph = coo_matrix(
                    (np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])),
                    shape=(len(vertices), len(vertices)),
                )
                count, labels = connected_components(graph, directed=False)
                components = [np.flatnonzero(labels == k) for k in range(count)]
            for indices in components:
                if len(indices) < (12 if g.get("fine_surface") else 35):
                    continue
                contributing = (
                    np.arange(len(g["frames"]))
                    if observation_ids is None
                    else np.unique(observation_ids[np.isin(voxel_ids, indices)])
                )
                source_frames = sorted({g["frames"][i] for i in contributing})
                score = round(float(np.mean(np.asarray(g["scores"])[contributing])), 4)
                points = vertices[indices]
                lo, hi = np.percentile(points, [1, 99], axis=0)
                center = np.median(points, axis=0) if g["instance"] else (lo + hi) / 2
                size = np.maximum(0.025, hi - lo)
                structural = kind in STRUCTURAL
                entrance = (
                    kind in {"door", "screen door"}
                    and size[1] > 1.2
                    and max(size[0], size[2]) > 0.4
                    and len(source_frames) >= 2
                )
                reliable = score >= 0.6 and len(source_frames) >= 3
                output_kind = (
                    kind if reliable or kind in {"wall", "floor", "ceiling"} else "unknown"
                )
                if kind in {"door", "screen door"} and not entrance:
                    output_kind = "unknown"
                label = f"{output_kind.replace('windowpane', 'window').title()} {len(objects) + 1}"
                if output_kind == "unknown":
                    label += f" (candidate: {kind})"
                if entrance:
                    label = f"Opening candidate {len(objects) + 1}"
                remap = np.full(len(vertices), -1, dtype=int)
                remap[indices] = np.arange(len(indices))
                selected_faces = faces[(remap[faces] >= 0).all(axis=1)]
                obj = SceneObject(
                    id=f"element-{len(objects) + 1:04}",
                    kind=output_kind,
                    label=label,
                    confidence=score,
                    method="RF-DETR tracked instance"
                    if g["instance"]
                    else "Semantic depth surface",
                    position=tuple(center),
                    size=tuple(size),
                    geometry=Geometry(
                        vertices=np.round(points - center, 4).tolist(),
                        colors=np.round(colors[indices], 3).tolist(),
                        triangles=remap[selected_faces].tolist(),
                    ),
                    structural=structural,
                    transient=g["transient"],
                    movable=not structural,
                    entrance=entrance,
                    source_frames=source_frames,
                    original_transform=Transform(position=tuple(center)),
                )
                if g.get("fine_surface"):
                    obj.method += "; adaptive pixel sampling for small surface"
                g["motion"]["object_ids"].append(obj.id)
                if g["transient"]:
                    obj.label = "Moving candidate: " + obj.label
                    obj.method += (
                        "; repeated motion residuals against camera/background; "
                        "single observed snapshot"
                    )
                fit_widths[obj.id] = 0.0  # Only fitted tables consume width evidence.
                if output_kind in {"table", "coffee table"}:
                    fit_widths[obj.id] = (
                        g["widths"][best]
                        if observation_ids is None
                        else component_width(g, np.isin(voxel_ids, indices), contributing)
                    )
                if output_kind == "light" and not obj.transient and observation_ids is not None:
                    selected_raw = np.isin(voxel_ids, indices)
                    offsets = np.r_[0, np.cumsum([len(p) for p in g["vertices"]])]
                    views = []
                    for i in contributing:
                        selected = selected_raw[offsets[i] : offsets[i + 1]]
                        if selected.sum() < 12:
                            continue
                        mapping = np.full(len(selected), -1, dtype=int)
                        mapping[selected] = np.arange(selected.sum())
                        triangles = g["triangles"][i] - offsets[i]
                        triangles = mapping[triangles]
                        triangles = triangles[(triangles >= 0).all(axis=1)]
                        view = dict(g["views"][i])
                        pose = view["pose"].copy()
                        pose[:3, :3] = R @ pose[:3, :3]
                        pose[:3, 3] = orient(pose[None, :3, 3])[0]
                        view.update(
                            pose=pose,
                            points=orient(g["vertices"][i][selected]),
                            colors=g["colors"][i][selected],
                            triangles=triangles,
                            score=g["scores"][i],
                        )
                        views.append(view)
                    fixture_observations[obj.id] = views
                objects.append(obj)
        floor = next((o.id for o in objects if o.kind == "floor"), None)
        walls = [o for o in objects if o.kind == "wall"]
        for obj in objects:
            if (
                not obj.transient
                and not obj.structural
                and floor
                and obj.position[1] - obj.size[1] / 2 < 0.3
            ):
                obj.supporting_surface = floor
            if obj.entrance or obj.kind == "windowpane":
                if walls:
                    obj.relationships = [f"boundary:{walls[0].id}"]
        survivors, merged_ids = fit_scene_furniture(objects, floor, fit_widths)
        self.merged += len(merged_ids)
        scene = Scene(
            objects=survivors, camera_path=orient(self.camera).tolist(), camera_frames=self.frames
        )
        from app.services.surfaces import refine_structures

        wall_observations = [
            (frame, orient(points))
            for g in self.groups
            if g["kind"] == "wall"
            for frame, points in zip(g["frames"], g["vertices"])
        ]
        scene, self.structure_report = refine_structures(scene, wall_observations)
        from app.services.fixtures import refine_ceiling_lights

        scene, self.fixture_report = refine_ceiling_lights(scene, fixture_observations)
        for merge in self.fixture_report["merges"]:
            merged_ids[merge["source_id"]] = merge["target_id"]
        self.merged += len(self.fixture_report["merges"])
        from app.services.openings import refine_openings

        opening_views = []
        if floor_found and any(obj.entrance for obj in scene.objects):
            for view in self.opening_views:
                pose = view["pose"].copy()
                pose[:3, :3] = R @ pose[:3, :3]
                pose[:3, 3] = orient(pose[None, :3, 3])[0]
                opening_views.append(dict(view, pose=pose))
        floor_ids = [
            key for key, label in self.labels.items() if label.split(",")[0].strip() == "floor"
        ]
        scene, self.opening_report = refine_openings(scene, opening_views, floor_ids)
        surviving_ids = {obj.id for obj in scene.objects}
        for entry in self.motion_report:
            resolved = set()
            for object_id in entry["object_ids"]:
                while object_id in merged_ids:
                    object_id = merged_ids[object_id]
                if object_id in surviving_ids:
                    resolved.add(object_id)
            entry["object_ids"] = sorted(resolved)
        return scene, floor_found


def component_width(group, selected, contributing):
    """Estimate apparent width using only this component's points in each source view.

    This preserves the existing pixel-span / focal-length times median-depth
    estimator, but excludes other components even when they share an observation.
    """
    offsets = np.r_[0, np.cumsum([len(points) for points in group["vertices"]])]
    widths = []
    for i in contributing:
        points = group["vertices"][i][selected[offsets[i] : offsets[i + 1]]]
        pose = group["views"][i]["pose"]
        camera = (points - pose[:3, 3]) @ pose[:3, :3]
        widths.append(float(np.ptp(camera[:, 0] / camera[:, 2]) * np.median(camera[:, 2])))
    return float(np.percentile(widths, 80))


def fit_scene_furniture(objects, floor, fit_widths):
    """Resolve table identities before using their centers to orient seating."""
    table_kinds = {"table", "coffee table"}
    for obj in objects:
        if obj.kind in table_kinds:
            fit_furniture(obj, floor, fit_widths[obj.id], [])
    objects, merged_ids = merge_furniture_surfaces(objects)
    table_centers = [
        np.asarray(obj.position) for obj in objects if obj.kind in table_kinds and not obj.transient
    ]
    for obj in objects:
        if obj.kind not in table_kinds:
            fit_furniture(obj, floor, fit_widths[obj.id], table_centers)
    survivors, seating_merges = merge_furniture_surfaces(objects)
    merged_ids.update(seating_merges)
    return survivors, merged_ids


def fit_furniture(obj, floor, width, table_centers):
    """Fit a static observed surface, retaining its original world-space evidence."""
    fit_kind = "table" if obj.kind == "coffee table" else obj.kind
    if obj.transient or fit_kind not in {"chair", "sofa", "table"} or obj.confidence < 0.6:
        return
    minimum_vertices = 35 if obj.kind == "chair" else 60
    if len(obj.source_frames) < 3 or len(obj.geometry.vertices) < minimum_vertices:
        return
    raw = np.asarray(obj.geometry.vertices)
    horizontal = raw[:, [0, 2]]
    _, axes = np.linalg.eigh(np.cov(horizontal.T))
    major = axes[:, -1]
    yaw = float(np.arctan2(-major[1], major[0]))
    if obj.kind == "chair" and table_centers:
        nearest = min(table_centers, key=lambda p: np.linalg.norm(p - np.array(obj.position)))
        toward = nearest - obj.position
        yaw = float(np.arctan2(toward[0], toward[2]))
    if obj.kind == "sofa" and table_centers:
        nearest = min(table_centers, key=lambda p: np.linalg.norm(p - np.array(obj.position)))
        toward = nearest - obj.position
        if np.dot([np.sin(yaw), 0, np.cos(yaw)], toward) < 0:
            yaw += np.pi
    rotation = Rotation.from_euler("y", yaw).as_matrix()
    local = raw @ rotation
    extents = np.percentile(local, 98, axis=0) - np.percentile(local, 2, axis=0)
    limits = {
        "chair": ([0.38, 0.78, 0.4], [0.8, 1.2, 0.85]),
        "sofa": ([0.85, 0.7, 0.65], [3.2, 1.15, 1.2]),
        "table": ([0.5, 0.55, 0.5], [2.7, 1.1, 2.7]),
    }
    extents[1] = np.percentile(raw[:, 1] + obj.position[1], 98)
    low, high = limits[fit_kind]
    dimensions = np.clip(extents, low, high)
    if fit_kind == "table":
        dimensions[0] = np.clip(width, 0.5, 2.7)
        dimensions[2] = min(dimensions[2], dimensions[0] * 1.1)
        dimensions[1] = min(dimensions[1], 0.85)
    # An observed floor anchors the support plane; otherwise leave the raw mesh.
    if floor is None:
        return
    original_position = np.asarray(obj.position)
    fitted_position = original_position.copy()
    fitted_position[1] = dimensions[1] / 2
    observed_local = ((raw + original_position) - fitted_position) @ rotation
    obj.observed_geometry = Geometry(
        vertices=observed_local.tolist(),
        colors=obj.geometry.colors,
        triangles=obj.geometry.triangles,
    )
    color = np.median(np.asarray(obj.geometry.colors), axis=0).tolist()
    obj.geometry = furniture(fit_kind, dimensions, color)
    obj.position = tuple(fitted_position)
    obj.rotation = (0, yaw, 0)
    obj.size = tuple(dimensions)
    obj.original_transform = Transform(position=obj.position, rotation=obj.rotation)
    obj.provenance = "primitive_fitted"
    obj.method = (
        obj.method + "; composite furniture fit "
        "with dimensional priors and floor support. Observed surface retained."
    )
    obj.supporting_surface = floor


def merge_furniture_surfaces(objects):
    """Merge overlapping semantic furniture evidence into supported fitted instances."""
    fitted = [o for o in objects if o.provenance == "primitive_fitted"]
    survivors = []
    merged_ids = {}
    for obj in objects:
        duplicate = False
        semantic_fit = obj.method.startswith("Semantic depth surface;")
        if (
            not obj.transient
            and (obj.provenance != "primitive_fitted" or semantic_fit)
            and obj.kind
            in {
                "sofa",
                "armchair",
                "ottoman",
                "chair",
                "table",
                "coffee table",
                "bed",
            }
        ):
            evidence = obj.observed_geometry or obj.geometry
            object_rotation = Rotation.from_euler("xyz", obj.rotation).as_matrix()
            world_points = (
                np.asarray(evidence.vertices) * obj.scale
            ) @ object_rotation.T + obj.position
            for target in fitted:
                if target.id == obj.id or (
                    semantic_fit and not target.method.startswith("RF-DETR")
                ):
                    continue
                family = (
                    {"sofa", "armchair", "ottoman", "bed"}
                    if target.kind == "sofa"
                    else {"table", "coffee table"}
                    if target.kind in {"table", "coffee table"}
                    else {target.kind}
                )
                if obj.kind not in family:
                    continue
                rotation = Rotation.from_euler("xyz", target.rotation).as_matrix()
                local = (world_points - target.position) @ rotation
                inside = (np.abs(local) <= np.asarray(target.size) * 0.65).all(axis=1)
                if inside.mean() > 0.7:
                    target.source_frames = sorted(set(target.source_frames + obj.source_frames))
                    duplicate = True
                    merged_ids[obj.id] = target.id
                    break
        if not duplicate:
            survivors.append(obj)
    return survivors, merged_ids


def stabilize_floor(vertices, tolerance=0.25):
    refined = vertices.copy()
    near = np.abs(refined[:, 1]) <= tolerance
    refined[near, 1] = 0
    return refined


def voxel_mesh(vertices, colors, faces, spacing=0.035, return_inverse=False):
    """Fuse redundant nearby observations, averaging color and removing duplicate faces."""
    _, inverse = np.unique(
        np.floor(vertices / spacing).astype(np.int32), axis=0, return_inverse=True
    )
    count = np.bincount(inverse)
    xyz = np.column_stack([np.bincount(inverse, weights=vertices[:, k]) / count for k in range(3)])
    rgb = np.column_stack([np.bincount(inverse, weights=colors[:, k]) / count for k in range(3)])
    triangles = inverse[faces]
    triangles = triangles[
        (triangles[:, 0] != triangles[:, 1])
        & (triangles[:, 1] != triangles[:, 2])
        & (triangles[:, 0] != triangles[:, 2])
    ]
    _, unique = np.unique(np.sort(triangles, axis=1), axis=0, return_index=True)
    result = (xyz, rgb, triangles[unique])
    return (*result, inverse) if return_inverse else result


def write_ply(scene, path):
    vertices = []
    colors = []
    for obj in scene.objects:
        if obj.deleted:
            continue
        rotation = Rotation.from_euler("xyz", obj.rotation).as_matrix()
        vertices.extend(
            ((np.asarray(obj.geometry.vertices) * obj.scale) @ rotation.T + obj.position).tolist()
        )
        colors.extend(obj.geometry.colors)
    with path.open("w") as file:
        file.write(
            f"ply\nformat ascii 1.0\nelement vertex {len(vertices)}\n"
            "property float x\nproperty float y\nproperty float z\n"
            "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        )
        for p, c in zip(vertices, colors):
            file.write(" ".join(map(str, [*p, *[round(v * 255) for v in c]])) + "\n")
