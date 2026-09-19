import numpy as np
import pytest

from app.services.geometry import Fusion, voxel_mesh


def split_surface(scores=(0.9, 0.9, 0.9, 0.99), shared=False):
    x, y = np.meshgrid(np.arange(9) * 0.06, np.arange(9) * 0.06)
    first = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, 3.0)))
    second = first + [3.0, 0, 0]
    points = [np.vstack([first, second])] * 3 if shared else [first] * 3 + [second]
    frames = [1, 2, 3] if shared else [1, 2, 3, 9]
    fusion = Fusion({0: "painting"})
    fusion.camera = [np.zeros(3)]
    fusion.frames = [1]
    fusion.groups = [
        dict(
            kind="painting",
            instance=False,
            vertices=points,
            colors=[np.full_like(p, 0.5) for p in points],
            triangles=[np.empty((0, 3), int) for _ in points],
            frames=frames,
            scores=list(scores[: len(frames)]),
            widths=[0.5] * len(frames),
            views=[],
        )
    ]
    scene, _ = fusion.finish()
    return sorted(scene.objects, key=lambda obj: obj.position[0])


@pytest.mark.parametrize("first_score", [0.4, 0.9])
def test_disconnected_fragment_cannot_borrow_frames_or_confidence(first_score):
    a, b = split_surface(scores=(first_score, first_score, first_score, 0.99))
    assert a.source_frames == [1, 2, 3]
    assert b.source_frames == [9]
    assert a.confidence == first_score
    assert b.confidence == 0.99
    assert a.kind == ("painting" if first_score >= 0.6 else "unknown")
    assert b.kind == "unknown"
    assert "candidate: painting" in b.label
    assert len(a.geometry.vertices) == len(b.geometry.vertices) == 81


def test_two_components_keep_shared_observations_after_voxel_fusion():
    a, b = split_surface(shared=True)
    assert a.source_frames == b.source_frames == [1, 2, 3]
    assert a.kind == b.kind == "painting"
    assert a.confidence == b.confidence == 0.9


def test_voxel_inverse_maps_each_raw_observation_to_its_emitted_vertex():
    points = np.array([[0.01, 0, 0], [0.012, 0, 0], [1, 0, 0]])
    colors = np.ones_like(points)
    faces = np.empty((0, 3), int)
    xyz, rgb, triangles, inverse = voxel_mesh(points, colors, faces, return_inverse=True)
    assert inverse.tolist() == [0, 0, 1]
    np.testing.assert_allclose(xyz[inverse], [[0.011, 0, 0], [0.011, 0, 0], [1, 0, 0]])
    legacy = voxel_mesh(points, colors, faces)
    for before, after in zip(legacy, [xyz, rgb, triangles]):
        np.testing.assert_array_equal(before, after)
