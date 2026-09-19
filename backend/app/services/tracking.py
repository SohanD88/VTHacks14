"""One-to-one 3D instance association across a complete localized frame."""

import numpy as np
from scipy.optimize import linear_sum_assignment


def associate_instances(observations, tracks, view=None):
    """Return one-to-one matches using distance and optional projected surface support.

    Optimize the whole frame so detection confidence/order cannot consume another
    object's only feasible track. Dummy columns allow every observation to remain
    unmatched; distinct instances visible together never share a track.
    """
    matches = {}
    kinds = {o["kind"] for o in observations if o["instance"]}
    for kind in kinds:
        rows = [i for i, o in enumerate(observations) if o["instance"] and o["kind"] == kind]
        columns = [i for i, t in enumerate(tracks) if t["instance"] and t["kind"] == kind]
        if not columns:
            continue
        threshold = 1.1 if kind == "sofa" else 0.65 if kind == "table" else 0.42
        centers = np.array([observations[i]["centroid"] for i in rows])
        previous = np.array([tracks[i]["centroid"] for i in columns])
        distances = np.linalg.norm(centers[:, None] - previous[None], axis=2)
        # Preserve distance-only behavior when camera/observation views are
        # unavailable. With views, reciprocal mask agreement disambiguates nearby
        # objects and admits bounded depth drift without abandoning spatial gates.
        feasible = distances < threshold
        normalized = distances / threshold
        if view is not None:
            normalized = np.minimum(normalized, 1.0) * 0.2 + 0.8
            for row, observation_id in enumerate(rows):
                observation = observations[observation_id]
                current = dict(view, mask=observation["selected"], step=observation["step"])
                for column, track_id in enumerate(columns):
                    if distances[row, column] > threshold * 2:
                        continue
                    track = tracks[track_id]
                    support = []
                    for k in range(max(0, len(track["views"]) - 3), len(track["views"])):
                        forward = surface_support(observation["pts"], track["views"][k])
                        backward = surface_support(track["vertices"][k], current)
                        support.append(min(forward, backward))
                    overlap = max(support, default=0.0)
                    feasible[row, column] |= overlap >= 0.55
                    normalized[row, column] -= overlap * 0.8
        # Maximize feasible matches, then minimize disagreement. Dummy columns
        # let observations remain unmatched; co-visible detections stay distinct.
        unmatched = len(rows) + 1.0
        cost = np.full((len(rows), len(columns) + len(rows)), unmatched)
        cost[:, : len(columns)] = np.where(feasible, normalized, unmatched * (len(rows) + 1))
        row_ids, column_ids = linear_sum_assignment(cost)
        for row, column in zip(row_ids, column_ids):
            if column < len(columns) and feasible[row, column]:
                matches[rows[row]] = columns[column]
    return matches


def surface_support(points, view):
    """Fraction of sampled world points projecting inside an observed mask.

    Out-of-frame and behind-camera points count as misses. Limit the sample count
    so association cost stays bounded even for dense foreground observations.
    """
    points = points[:: max(1, (len(points) + 249) // 250)]
    if not len(points):
        return 0.0
    pose, mask = view["pose"], view["mask"]
    camera = (points - pose[:3, 3]) @ pose[:3, :3]
    projected = camera @ view["K"].T
    pixels = np.rint(projected[:, :2] / np.maximum(projected[:, 2:], 0.01) / view["step"]).astype(
        int
    )
    visible = (
        (camera[:, 2] > 0.1)
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] < mask.shape[1])
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < mask.shape[0])
    )
    hits = np.zeros(len(points), bool)
    hits[visible] = mask[pixels[visible, 1], pixels[visible, 0]]
    return float(hits.mean())


def projected_overlap(source, target):
    """Median source-surface support inside another track's observed image masks."""
    source_ids = sorted(
        range(len(source["vertices"])), key=lambda i: len(source["vertices"][i]), reverse=True
    )[:3]
    target_ids = sorted(
        range(len(target["vertices"])), key=lambda i: len(target["vertices"][i]), reverse=True
    )[:3]
    support = []
    for i in source_ids:
        points = source["vertices"][i]
        points = points[:: max(1, len(points) // 300)]
        for j in target_ids:
            view = target["views"][j]
            pose, mask = view["pose"], view["mask"]
            camera = (points - pose[:3, 3]) @ pose[:3, :3]
            projected = camera @ view["K"].T
            pixels = np.rint(
                projected[:, :2] / np.maximum(projected[:, 2:], 0.01) / view["step"]
            ).astype(int)
            visible = (
                (camera[:, 2] > 0.1)
                & (pixels[:, 0] >= 0)
                & (pixels[:, 0] < mask.shape[1])
                & (pixels[:, 1] >= 0)
                & (pixels[:, 1] < mask.shape[0])
            )
            hits = np.zeros(len(points), bool)
            hits[visible] = mask[pixels[visible, 1], pixels[visible, 0]]
            support.append(float(hits.mean()))
    return float(np.median(support)) if support else 0.0


def consolidate_instances(groups):
    """Merge disjoint tracks supported by reciprocal image-space surface overlap.

    Co-visible tracks cannot merge, including through a chain of intermediate
    tracks. Keep all original observations and rebase their triangle indices.
    """
    candidates = []
    for i, a in enumerate(groups):
        if not a["instance"]:
            continue
        for j, b in enumerate(groups[:i]):
            if not b["instance"] or a["kind"] != b["kind"]:
                continue
            if set(a["frames"]) & set(b["frames"]):
                continue
            limit = {"chair": 1.1, "table": 1.2, "sofa": 1.5}.get(a["kind"], 0.7)
            if np.linalg.norm(a["centroid"] - b["centroid"]) > limit:
                continue
            color_a = np.median(np.concatenate(a["colors"]), axis=0)
            color_b = np.median(np.concatenate(b["colors"]), axis=0)
            if np.linalg.norm(color_a - color_b) > 0.35:
                continue
            forward, backward = projected_overlap(a, b), projected_overlap(b, a)
            if min(forward, backward) >= 0.55:
                candidates.append((min(forward, backward), j, i, forward, backward))
    parent = list(range(len(groups)))
    members = {i: {i} for i in range(len(groups))}
    report = []

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for _, a_id, b_id, forward, backward in sorted(candidates, reverse=True):
        i, j = root(a_id), root(b_id)
        if i == j:
            continue
        a, b = groups[i], groups[j]
        if set(a["frames"]) & set(b["frames"]):
            continue
        report.append(
            dict(
                kind=a["kind"],
                tracks=sorted(members[i] | members[j]),
                source_frames=sorted(set(a["frames"] + b["frames"])),
                reciprocal_overlap=[round(forward, 4), round(backward, 4)],
            )
        )
        offset = sum(len(points) for points in a["vertices"])
        a["triangles"].extend(faces + offset for faces in b["triangles"])
        for key in ["vertices", "colors", "scores", "frames", "widths", "views"]:
            a[key].extend(b[key])
        a["lo"], a["hi"] = np.minimum(a["lo"], b["lo"]), np.maximum(a["hi"], b["hi"])
        a["centroid"] = np.median(np.array([np.median(v, axis=0) for v in a["vertices"]]), axis=0)
        parent[j] = i
        members[i] |= members[j]
    return [group for i, group in enumerate(groups) if parent[i] == i], report
