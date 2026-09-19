import numpy as np

from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.surfaces import refine_structures, surface_normals, wall_planes


def patches():
    """Disconnected short fins line up spatially but do not form a shared wall."""
    points, faces = [], []
    for x in np.linspace(0, 5, 12):
        y, z = np.meshgrid(np.linspace(0, 2, 25), np.linspace(-0.08, 0.08, 8))
        offset = len(points)
        points.extend(np.column_stack((np.full(y.size, x), y.ravel(), z.ravel())))
        for i in range(7):
            for j in range(24):
                a = offset + i * 25 + j
                faces.extend([[a, a + 1, a + 26], [a, a + 26, a + 25]])
    return np.asarray(points), np.asarray(faces)


def test_plane_cannot_cut_across_unrelated_surface_orientations():
    points, faces = patches()
    normals, reliable = surface_normals(points, faces)
    # Positional RANSAC alone incorrectly spans the disconnected fins.
    assert len(wall_planes(points)) >= 1
    assert reliable.all()
    assert np.allclose(np.abs(normals[:, 0]), 1)
    assert wall_planes(points, normals, reliable) == []
    original = SceneObject(
        id="wall",
        kind="wall",
        label="Wall observations",
        confidence=0.9,
        position=(0, 0, 0),
        size=(5, 2, 0.16),
        structural=True,
        movable=False,
        geometry=Geometry(
            vertices=points.tolist(), colors=[[0.5] * 3] * len(points), triangles=faces.tolist()
        ),
        original_transform=Transform(),
        source_frames=[0, 1, 2],
    )
    scene, report = refine_structures(Scene(objects=[original]))
    assert report["wall_planes"] == 0
    assert scene.objects[0].geometry == original.geometry


def test_normals_ignore_triangle_winding_and_reject_degenerate_vertices():
    points, faces = patches()
    expected, valid = surface_normals(points, faces)
    reversed_faces = faces.copy()
    reversed_faces[::2] = reversed_faces[::2, ::-1]
    actual, actual_valid = surface_normals(points, reversed_faces)
    assert np.array_equal(valid, actual_valid)
    assert np.allclose(np.abs((actual * expected).sum(axis=1)), 1)
    extended = np.vstack([points, [9, 9, 9]])
    _, valid = surface_normals(extended, np.vstack([faces, [len(points)] * 3]))
    assert not valid[-1]


def test_oriented_wall_retains_observed_door_gap_and_raw_faces():
    x, y = np.meshgrid(np.arange(0, 3, 0.04), np.arange(0, 3, 0.04))
    points = np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size)))
    faces = []
    for i in range(x.shape[0] - 1):
        for j in range(x.shape[1] - 1):
            if 1 < x[i, j] < 2 and y[i, j] < 2:
                continue
            a = i * x.shape[1] + j
            faces.extend([[a, a + 1, a + x.shape[1] + 1], [a, a + x.shape[1] + 1, a + x.shape[1]]])
    faces = np.asarray(faces)
    ids = np.unique(faces)
    mapping = np.full(len(points), -1)
    mapping[ids] = np.arange(len(ids))
    points = points[ids]
    faces = mapping[faces]
    obj = SceneObject(
        id="wall",
        kind="wall",
        label="Wall",
        confidence=0.9,
        position=(0, 0, 0),
        size=(3, 3, 0.025),
        structural=True,
        movable=False,
        source_frames=[0, 1, 2],
        original_transform=Transform(),
        geometry=Geometry(
            vertices=points.tolist(), colors=[[0.5] * 3] * len(points), triangles=faces.tolist()
        ),
    )
    scene, report = refine_structures(Scene(objects=[obj], camera_path=[(1, 1, 2)]))
    assert report["wall_planes"] == 1
    assert report["plane_orientation_support"][0]["median_normal_agreement"] > 0.99
    wall = scene.objects[0]
    assert len(wall.observed_geometry.vertices) == len(points)
    world = np.asarray(wall.geometry.vertices) + wall.position
    centers = world[np.asarray(wall.geometry.triangles)].mean(axis=1)
    assert not ((centers[:, 0] > 1.15) & (centers[:, 0] < 1.85) & (centers[:, 1] < 1.8)).any()
    assert wall.observed_geometry.triangles == obj.geometry.triangles
