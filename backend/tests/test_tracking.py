import numpy as np

from app.services.tracking import associate_instances


def observation(x, kind="chair", instance=True):
    return dict(kind=kind, instance=instance, centroid=np.array([x, 0.0, 0.0]))


def test_joint_assignment_avoids_greedy_track_theft_and_order_dependence():
    tracks = [observation(0), observation(0.5)]
    # First detection could use either track; second can only use track zero.
    views = [observation(0.2), observation(-0.2)]
    assert associate_instances(views, tracks) == {0: 1, 1: 0}
    assert associate_instances(views[::-1], tracks) == {0: 0, 1: 1}


def test_simultaneous_instances_do_not_share_a_track_or_force_distant_matches():
    views = [observation(0.1), observation(0.2), observation(2)]
    assert associate_instances(views, [observation(0)]) == {0: 0}


def test_class_identity_semantic_regions_and_empty_history_are_preserved():
    views = [observation(0), observation(0, "table"), observation(0, instance=False)]
    assert associate_instances(views, [observation(0, "table")]) == {1: 0}
    assert associate_instances(views, []) == {}
    assert associate_instances([], [observation(0)]) == {}


def surface_track(frames, depth=3.0, pixel_shift=0):
    K = np.array([[100, 0, 50], [0, 100, 50], [0, 0, 1.0]])
    x, y = np.meshgrid(np.arange(25, 40, 3) + pixel_shift, np.arange(35, 60, 3))
    pixels = np.column_stack((x.ravel(), y.ravel()))
    points = np.column_stack(((pixels - 50) * depth / 100, np.full(len(pixels), depth)))
    mask = np.zeros((100, 100), bool)
    mask[33:62, 23 + pixel_shift : 42 + pixel_shift] = True
    return dict(
        kind="chair",
        instance=True,
        centroid=points.mean(axis=0),
        vertices=[points.copy() for _ in frames],
        colors=[np.full_like(points, 0.5) for _ in frames],
        triangles=[np.array([[0, 1, 2]]) + i * len(points) for i in range(len(frames))],
        views=[dict(pose=np.eye(4), K=K, mask=mask, step=1) for _ in frames],
        scores=[0.8] * len(frames),
        frames=frames,
        widths=[0.5] * len(frames),
        lo=points.min(axis=0),
        hi=points.max(axis=0),
    )


def test_reciprocal_projection_merges_depth_shift_preserving_evidence_and_faces():
    from app.services.tracking import consolidate_instances

    first, second = surface_track([1, 2]), surface_track([3, 4], depth=3.6)
    expected_points = np.concatenate(first["vertices"] + second["vertices"])
    groups, report = consolidate_instances([first, second])
    assert len(groups) == 1 and len(report) == 1
    assert set(groups[0]["frames"]) == {1, 2, 3, 4}
    np.testing.assert_allclose(np.concatenate(groups[0]["vertices"]), expected_points)
    triangles = np.concatenate(groups[0]["triangles"])
    assert len(np.unique(triangles)) == 12
    assert triangles.max() < len(expected_points)
    assert min(report[0]["reciprocal_overlap"]) >= 0.55


def test_nearby_distinct_chairs_and_covisible_tracks_are_not_merged():
    from app.services.tracking import consolidate_instances

    groups, report = consolidate_instances([surface_track([1]), surface_track([2], pixel_shift=25)])
    assert len(groups) == 2 and report == []
    groups, report = consolidate_instances([surface_track([1, 2]), surface_track([2, 3])])
    assert len(groups) == 2 and report == []


def test_chain_of_matches_cannot_merge_tracks_seen_together():
    from app.services.tracking import consolidate_instances

    groups, report = consolidate_instances(
        [surface_track([1]), surface_track([2], depth=3.1), surface_track([1], depth=3.2)]
    )
    assert len(groups) == 2 and len(report) == 1
    assert all(len(g["frames"]) == len(set(g["frames"])) for g in groups)


def current_observation(track):
    return dict(
        kind=track["kind"],
        instance=True,
        centroid=track["centroid"].copy(),
        pts=track["vertices"][0],
        selected=track["views"][0]["mask"],
        step=1,
    )


def test_projected_masks_prevent_nearby_identity_swap_from_depth_centroids():
    left, right = surface_track([1]), surface_track([1], pixel_shift=12)
    observations = [current_observation(left), current_observation(right)]
    # Partial occlusion/depth error makes each observed centroid nearer the wrong track.
    observations[0]["centroid"] = right["centroid"].copy()
    observations[1]["centroid"] = left["centroid"].copy()
    assert associate_instances(observations, [left, right]) == {0: 1, 1: 0}
    view = left["views"][0]
    assert associate_instances(observations, [left, right], view) == {0: 0, 1: 1}
    assert associate_instances(observations[::-1], [left, right], view) == {0: 1, 1: 0}


def test_reciprocal_projection_allows_bounded_depth_drift_but_not_distant_aliases():
    first = surface_track([1])
    shifted = current_observation(surface_track([2], depth=3.6))
    assert associate_instances([shifted], [first]) == {}
    assert associate_instances([shifted], [first], first["views"][0]) == {0: 0}
    distant = current_observation(surface_track([2], depth=5))
    assert associate_instances([distant], [first], first["views"][0]) == {}
    # Two detections remain separate even when both could explain one old track.
    result = associate_instances([shifted, shifted], [first], first["views"][0])
    assert len(result) == 1


def test_projection_support_counts_hidden_outside_and_empty_points_as_misses():
    from app.services.tracking import surface_support

    track = surface_track([1])
    points, view = track["vertices"][0], track["views"][0]
    assert surface_support(points, view) == 1
    assert surface_support(-points, view) == 0
    assert surface_support(points + [100, 0, 0], view) == 0
    assert surface_support(points[:0], view) == 0
