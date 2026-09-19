"""Joint registration must improve shared observations without fabricating poses."""

import numpy as np

from app.services.registration import project, refine_views


def test_joint_registration_reduces_known_pose_and_depth_errors():
    rng = np.random.default_rng(72)
    world = rng.uniform([-1, -1, 4], [1, 1, 7], (80, 3))
    descriptors = rng.uniform(0, 255, (80, 128)).astype(np.float32)
    K = np.array([[400.0, 0, 250], [0, 380.0, 250], [0, 0, 1]])
    views = []
    for i in range(4):
        position = np.array([0.15 * i, 0, 0])
        camera = world - position
        pose = np.eye(4)
        pose[:3, 3] = position + [0.025 * i, 0.004 * i, 0]
        views.append(
            dict(
                pose=pose,
                K=K,
                xyz=camera * (1 + 0.025 * i),
                pixels=project(camera, K),
                descriptors=descriptors,
            )
        )
    poses, scales, report = refine_views(views)
    assert report["accepted"]
    assert report["after"]["median_3d_m"] < report["before"]["median_3d_m"] / 3
    assert report["after"]["median_reprojection_px"] < report["before"]["median_reprojection_px"]
    np.testing.assert_array_equal(poses[0], views[0]["pose"])
    assert scales[0] == 1
    assert len(poses) == len(views)
    assert np.isfinite(poses).all()


def test_refinement_does_not_add_missing_views():
    pose = np.eye(4)
    result, scales, report = refine_views([{"pose": pose}])
    assert not report["accepted"]
    assert len(result) == 1
    np.testing.assert_array_equal(result[0], pose)
    np.testing.assert_array_equal(scales, [1])
