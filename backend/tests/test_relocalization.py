import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.services.relocalization import recover_views


def scene_views():
    rng = np.random.default_rng(719)
    world = rng.uniform([-1.0, -1.5, 2.5], [1.0, 1.5, 5.0], (100, 3))
    descriptors = rng.uniform(0, 200, (100, 128)).astype(np.float32)
    K = np.array([[440.0, 0, 145], [0, 440.0, 259], [0, 0, 1]])
    views = []
    for frame, x, angle in [(1, 0.0, 0.0), (2, 0.15, 0.03), (3, 0.4, 0.1)]:
        pose = np.eye(4)
        pose[:3, :3] = Rotation.from_euler("y", angle).as_matrix()
        pose[0, 3] = x
        xyz = (world - pose[:3, 3]) @ pose[:3, :3]
        projected = xyz @ K.T
        views.append(
            dict(
                frame=frame,
                pose=pose,
                K=K,
                xyz=xyz,
                pixels=(projected[:, :2] / projected[:, 2:]).astype(np.float32),
                descriptors=descriptors.copy(),
            )
        )
    expected = views[2]["pose"].copy()
    del views[2]["pose"]
    views[2]["xyz"] /= 1.1
    return views[:2], views[2:], expected


def test_supported_pose_recovery_preserves_coordinate_system_and_aligns_depth():
    accepted, pending, expected = scene_views()
    before = pending[0]["xyz"].copy()
    recovered, report = recover_views(accepted, pending)
    assert len(recovered) == len(report) == 1
    np.testing.assert_allclose(recovered[0]["pose"], expected, atol=1e-5)
    np.testing.assert_allclose(recovered[0]["xyz"], before * 1.1, atol=1e-5)
    np.testing.assert_array_equal(pending[0]["xyz"], before)
    assert set(report[0]["reference_frames"]) == {1, 2}
    assert report[0]["inliers"] == 100
    assert report[0]["reprojection_px"] < 0.001


def test_single_reference_and_disconnected_views_are_not_enough():
    accepted, pending, _ = scene_views()
    assert recover_views(accepted[:1], pending) == ([], [])
    assert recover_views([], pending) == ([], [])
    pending[0]["descriptors"] = None
    assert recover_views(accepted, pending) == ([], [])


def test_disagreeing_world_poses_are_rejected_even_with_good_individual_matches():
    accepted, pending, _ = scene_views()
    accepted[1]["pose"][0, 3] += 0.75
    assert recover_views(accepted, pending) == ([], [])


def test_narrow_image_support_cannot_recover_a_room_view():
    accepted, pending, _ = scene_views()
    # Keep corresponding 3D points, but compress all camera projections to a narrow strip.
    for view in accepted + pending:
        view["xyz"][:, 1] *= 0.01
        view["pixels"][:, 1] = 259 + (view["pixels"][:, 1] - 259) * 0.01
    assert recover_views(accepted, pending) == ([], [])


def test_relocalization_remains_cancellable():
    accepted, pending, _ = scene_views()

    def cancel():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        recover_views(accepted, pending, cancel)
