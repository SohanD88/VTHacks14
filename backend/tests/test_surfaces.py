import warnings

import numpy as np

from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.surfaces import refine_structures


def test_observed_wall_fit_preserves_door_gap_raw_evidence_and_protection():
    rng = np.random.default_rng(8)
    x, y = np.meshgrid(np.arange(0, 3, 0.025), np.arange(0, 3, 0.025))
    visible = ~((x > 1) & (x < 2) & (y < 2))
    points = np.column_stack((x[visible], y[visible], rng.normal(0, 0.035, visible.sum())))
    original = SceneObject(
        id="wall",
        kind="wall",
        label="Wall",
        confidence=0.85,
        position=(0, 0, 0),
        size=(3, 3, 0.2),
        structural=True,
        movable=False,
        source_frames=[0, 1, 2],
        original_transform=Transform(),
        geometry=Geometry(vertices=points.tolist(), colors=[[0.5, 0.7, 0.3]] * len(points)),
    )
    scene, report = refine_structures(Scene(objects=[original], camera_path=[(1, 1, 3)]))
    assert report["wall_planes"] == 1
    wall = scene.objects[0]
    assert wall.structural and not wall.movable
    assert wall.provenance == "primitive_fitted"
    assert wall.observed_geometry is not None
    vertices = np.array(wall.geometry.vertices) + wall.position
    centers = vertices[np.array(wall.geometry.triangles)].mean(axis=1)
    assert not ((centers[:, 0] > 1.1) & (centers[:, 0] < 1.9) & (centers[:, 1] < 1.9)).any()
    assert np.ptp(vertices[:, 2]) < 0.02
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Scene.model_validate_json(scene.model_dump_json())


def test_small_or_unusable_structure_is_not_replaced():
    obj = SceneObject(
        id="wall",
        kind="wall",
        label="Wall",
        confidence=0.4,
        position=(0, 0, 0),
        size=(1, 1, 1),
        original_transform=Transform(),
    )
    scene, report = refine_structures(Scene(objects=[obj]))
    assert report["wall_planes"] == 0
    assert scene.objects[0] == obj


def corner_wall(id, normal, start=0.12, end=2.0, missing_band=False):
    from app.services.surfaces import footprint_mesh

    normal = np.asarray(normal, dtype=float)
    tangent = np.array([normal[2], 0, -normal[0]])
    width, height = np.meshgrid(np.arange(start, end, 0.03), np.arange(0, 2, 0.03))
    valid = np.ones(width.shape, bool)
    if missing_band:
        valid &= (height < 0.75) | (height > 1.25)
    points = width[valid, None] * tangent + height[valid, None] * np.array([0, 1, 0])
    mesh = footprint_mesh(points, np.full_like(points, 0.6), normal, np.zeros(3))
    wall = SceneObject(
        id=id,
        kind="wall",
        label=id,
        confidence=0.8,
        position=(0, 0, 0),
        size=(2, 2, 2),
        geometry=mesh,
        observed_geometry=mesh.model_copy(deep=True),
        structural=True,
        movable=False,
        provenance="primitive_fitted",
        original_transform=Transform(),
    )
    return wall, normal, np.zeros(3)


def test_corner_seam_joins_supported_edges_and_preserves_missing_height_band():
    from app.services.surfaces import join_observed_corners

    a = corner_wall("a", [0, 0, 1])
    b = corner_wall("b", [1, 0, 0], missing_band=True)
    raw = [plane[0].observed_geometry.model_dump() for plane in [a, b]]
    report = join_observed_corners([a, b])
    assert len(report) == 1
    assert report[0]["maximum_displacement"] <= 0.31
    junction_heights = []
    for wall, _, _ in [a, b]:
        vertices = np.asarray(wall.geometry.vertices)
        seam = np.linalg.norm(vertices[:, [0, 2]], axis=1) < 1e-5
        junction_heights.append(set(vertices[seam, 1]))
        faces = vertices[np.asarray(wall.geometry.triangles)]
        assert (
            np.linalg.norm(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]), axis=1)
            > 0
        ).all()
    common = junction_heights[0] & junction_heights[1]
    assert len(common) >= 8
    assert not any(0.85 < y < 1.15 for y in common)
    assert a[0].relationships == ["adjacent:b"]
    assert b[0].relationships == ["adjacent:a"]
    assert raw == [plane[0].observed_geometry.model_dump() for plane in [a, b]]
    Scene.model_validate_json(Scene(objects=[a[0], b[0]]).model_dump_json())


def test_corner_seam_does_not_close_unobserved_gaps_or_collapse_interiors():
    from app.services.surfaces import join_observed_corners

    for second in [corner_wall("b", [1, 0, 0], start=0.7), corner_wall("b", [0, 0, 1])]:
        first = corner_wall("a", [0, 0, 1])
        before = first[0].geometry.model_dump()
        assert join_observed_corners([first, second]) == []
        assert first[0].geometry.model_dump() == before
    # Crossing planes already meet internally; they are not missing corner edges.
    assert (
        join_observed_corners(
            [
                corner_wall("a", [0, 0, 1], start=-1, end=1),
                corner_wall("b", [1, 0, 0], start=-1, end=1),
            ]
        )
        == []
    )
