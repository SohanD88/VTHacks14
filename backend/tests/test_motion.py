import numpy as np

from app.services.motion import MotionAnalyzer, geometric_residuals


def sequence(moving=True, translating=True, depth_noise=False, sparse=False, count=16):
    rng = np.random.default_rng(3)
    count = 4 if sparse else count
    foreground = np.c_[
        rng.uniform(-0.8, -0.3, count), rng.uniform(-0.4, -0.1, count), np.full(count, 3)
    ]
    background = np.c_[rng.uniform(0.3, 1.6, 80), rng.uniform(-1.5, 1.5, 80), rng.uniform(3, 6, 80)]
    base = np.r_[foreground, background]
    descriptors = rng.normal(size=(len(base), 128)).astype(np.float32)
    K = np.array([[170, 0, 100], [0, 150, 100], [0, 0, 1.0]])
    features, views = {}, []
    for frame in range(3):
        pose = np.eye(4)
        pose[0, 3] = frame * 0.06 if translating else 0
        xyz = base.copy()
        if moving:
            xyz[:count, 1] += frame * 0.22
        camera = xyz - pose[:3, 3]
        projected = camera @ K.T
        pixels = projected[:, :2] / projected[:, 2:]
        mask = np.zeros((220, 220), bool)
        low, high = (
            np.floor(pixels[:count].min(axis=0)).astype(int) - 4,
            np.ceil(pixels[:count].max(axis=0)).astype(int) + 5,
        )
        mask[low[1] : high[1], low[0] : high[0]] = True
        features[frame] = dict(
            pose=pose,
            K=K,
            pixels=pixels,
            descriptors=descriptors,
            xyz=camera * (0.6 + 0.5 * frame if depth_noise else 1),
        )
        views.append(dict(frame=frame, pose=pose, K=K, mask=mask, step=1))
    return features, views


def test_moving_object_requires_repeated_geometric_evidence():
    features, views = sequence()
    result = MotionAnalyzer(features).assess(views)
    assert result["status"] == "moving_candidate"
    assert result["consecutive_motion_pairs"] == 2
    assert all(
        pair["matches"] == 16 and pair["background_p90_px"] < 0.001 for pair in result["pairs"]
    )
    assert MotionAnalyzer(features).assess(views[:2])["status"] == "insufficient_evidence"


def test_stationary_camera_detects_independent_object_motion():
    features, views = sequence(translating=False)
    result = MotionAnalyzer(features).assess(views)
    assert result["status"] == "moving_candidate"
    assert all(pair["method"] == "rotation" for pair in result["pairs"])


def test_static_object_remains_static_despite_camera_motion_and_depth_scale_noise():
    features, views = sequence(moving=False, depth_noise=True)
    result = MotionAnalyzer(features).assess(views)
    assert result["status"] == "consistent"
    assert all(pair["median_residual_px"] < 0.001 for pair in result["pairs"])


def test_sparse_evidence_and_bad_background_pose_abstain():
    features, views = sequence(sparse=True)
    assert MotionAnalyzer(features).assess(views)["status"] == "insufficient_evidence"
    features, views = sequence()
    features[1]["pose"][1, 3] = 0.7
    assert MotionAnalyzer(features).assess(views)["status"] == "insufficient_evidence"


def test_epipolar_aligned_motion_is_not_claimed_detectable():
    features, _ = sequence(moving=False)
    p0, p1 = features[0]["pixels"], features[1]["pixels"].copy()
    p1[:16, 0] += 15
    residual, method = geometric_residuals(features[0], features[1], p0, p1)
    assert method == "epipolar" and residual.max() < 1e-6


def test_fusion_retains_moving_object_as_one_unfitted_transient_snapshot():
    from app.services.geometry import Fusion

    features, views = sequence(count=64)
    points = [f["xyz"][:64] @ f["pose"][:3, :3].T + f["pose"][:3, 3] for f in features.values()]
    fusion = Fusion({0: "chair"})
    fusion.features = features
    fusion.camera = [f["pose"][:3, 3] for f in features.values()]
    fusion.frames = list(features)
    fusion.groups = [
        dict(
            kind="chair",
            instance=True,
            vertices=points,
            colors=[np.full_like(p, 0.5) for p in points],
            triangles=[np.array([[0, 1, 2]]) + i * 64 for i in range(3)],
            frames=list(features),
            views=views,
            scores=[0.9] * 3,
            widths=[0.5] * 3,
            centroid=points[-1].mean(axis=0),
            lo=np.concatenate(points).min(axis=0),
            hi=np.concatenate(points).max(axis=0),
        )
    ]
    scene, _ = fusion.finish()
    assert len(scene.objects) == 1
    obj = scene.objects[0]
    assert obj.transient and obj.kind == "chair"
    assert obj.provenance == "depth_inferred" and obj.observed_geometry is None
    assert len(obj.geometry.vertices) <= 64
    assert "single observed snapshot" in obj.method
    assert obj.source_frames == [0, 1, 2]
    assert fusion.motion_report[0]["status"] == "moving_candidate"
