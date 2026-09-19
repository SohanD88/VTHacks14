import numpy as np

from app.services.geometry import Fusion


def fixture_frames(count=3, confidence=0.9, second_x=60):
    rgb = np.full((100, 100, 3), 240, np.uint8)
    depth = np.full((100, 100), 2.0)
    labels = np.zeros((100, 100), np.uint8)
    labels[20:28, 15:23] = 1
    labels[20:28, second_x : second_x + 8] = 1
    fusion = Fusion({0: "person", 1: "light"})
    for frame in range(count):
        fusion.add(rgb, depth, labels, np.full_like(depth, confidence), np.eye(4), frame)
    return fusion


def test_small_lights_survive_meshing_with_separate_identity_and_source_evidence():
    fusion = fixture_frames()
    scene, _ = fusion.finish()
    assert len(scene.objects) == 2
    assert all(o.kind == "light" and o.source_frames == [0, 1, 2] for o in scene.objects)
    assert all(len(o.geometry.triangles) > 0 for o in scene.objects)
    assert all(o.provenance == "depth_inferred" for o in scene.objects)
    assert all("adaptive pixel sampling" in o.method for o in scene.objects)
    assert abs(scene.objects[0].position[0] - scene.objects[1].position[0]) > 0.9


def test_single_view_small_surfaces_remain_uncertain_and_low_confidence_is_rejected():
    scene, _ = fixture_frames(count=1).finish()
    assert len(scene.objects) == 2
    assert all(o.kind == "unknown" and o.source_frames == [0] for o in scene.objects)
    assert all("candidate: light" in o.label for o in scene.objects)
    scene, _ = fixture_frames(confidence=0.2).finish()
    assert scene.objects == []


def test_rescue_does_not_duplicate_large_regions_or_promote_tiny_noise():
    from app.services.sampling import small_observations

    rgb = np.zeros((100, 100, 3), np.uint8)
    depth = np.full((100, 100), 2.0)
    labels = np.zeros((100, 100), np.uint8)
    labels[10:50, 10:50] = 1
    labels[80:83, 80:83] = 1
    observations = small_observations(
        rgb,
        depth,
        labels,
        np.ones_like(depth),
        np.eye(4),
        np.eye(3),
        {0: "person", 1: "light"},
        5,
        {"person"},
    )
    assert observations == []


def test_region_triangles_preserve_holes_and_reject_depth_discontinuities():
    from app.services.sampling import region_triangles

    selected = np.ones((7, 7), bool)
    selected[2:5, 2:5] = False
    y, x = np.nonzero(selected)
    points = np.column_stack((x * 0.05, y * 0.05, np.where(x < 3, 2, 3)))
    faces = region_triangles(selected, points)
    assert len(faces) > 0
    corners = points[faces]
    assert np.max(np.linalg.norm(corners - np.roll(corners, 1, axis=1), axis=2)) < 0.35
    # Every triangle remains within one observed pixel cell and one depth layer.
    assert np.ptp(x[faces], axis=1).max() == 1
    assert np.ptp(y[faces], axis=1).max() == 1
    assert np.ptp(corners[:, :, 2], axis=1).max() == 0


def test_nearby_small_surfaces_seen_together_remain_distinct():
    scene, _ = fixture_frames(second_x=27).finish()
    assert len(scene.objects) == 2
    assert all(o.source_frames == [0, 1, 2] for o in scene.objects)
    separation = abs(scene.objects[0].position[0] - scene.objects[1].position[0])
    assert 0.2 < separation < 0.35
