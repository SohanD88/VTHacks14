import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, SceneObject, Transform
from app.services.geometry import fit_scene_furniture, merge_furniture_surfaces


def surface(id, kind, position, semantic=False, transient=False):
    x, z = np.meshgrid(np.linspace(-0.2, 0.2, 9), np.linspace(-0.15, 0.15, 9))
    points = np.column_stack((x.ravel(), np.zeros(x.size), z.ravel()))
    return SceneObject(
        id=id,
        label=id,
        kind=kind,
        confidence=0.9,
        position=position,
        size=(0.4, 0.1, 0.3),
        geometry=Geometry(vertices=points.tolist(), colors=np.full_like(points, 0.5).tolist()),
        original_transform=Transform(position=position),
        source_frames=[1, 2, 3],
        method="Semantic depth surface" if semantic else "RF-DETR tracked instance",
        transient=transient,
    )


def fit(objects):
    return fit_scene_furniture(objects, "floor", {o.id: 2.0 for o in objects})


def world_observations(obj):
    evidence = obj.observed_geometry or obj.geometry
    return (
        np.asarray(evidence.vertices) @ Rotation.from_euler("xyz", obj.rotation).as_matrix().T
        + obj.position
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_chair_faces_surviving_table_and_retains_world_observations(reverse):
    chair = surface("chair", "chair", (1.4, 0.7, 0.2))
    table = surface("table", "table", (0, 0.7, 0))
    fragment = surface("fragment", "table", (0.3, 0.7, 0.2), semantic=True)
    before = world_observations(chair).copy()
    objects = [chair, fragment, table]
    survivors, merged = fit(objects[::-1] if reverse else objects)
    assert merged == {"fragment": "table"}
    assert {o.id for o in survivors} == {"chair", "table"}
    toward = np.asarray(table.position) - chair.position
    assert chair.rotation[1] == pytest.approx(np.arctan2(toward[0], toward[2]))
    assert chair.original_transform.rotation == chair.rotation
    np.testing.assert_allclose(world_observations(chair), before, atol=1e-12)


def test_genuine_distinct_nearby_table_is_used():
    chair = surface("chair", "chair", (2, 0.7, 0.5))
    distant = surface("distant", "table", (-2, 0.7, 0))
    nearby = surface("nearby", "coffee table", (2, 0.7, -1), semantic=True)
    survivors, merged = fit([chair, distant, nearby])
    assert len(survivors) == 3 and merged == {}
    assert abs(chair.rotation[1]) == pytest.approx(np.pi)


def test_moving_table_does_not_orient_static_seating():
    chair = surface("chair", "chair", (1, 0.7, 0))
    static = surface("static", "table", (-2, 0.7, 0))
    moving = surface("moving", "table", (1, 0.7, 0.2), transient=True)
    before = moving.model_dump()
    survivors, merged = fit([chair, static, moving])
    assert len(survivors) == 3 and merged == {}
    assert chair.rotation[1] == pytest.approx(-np.pi / 2)
    assert moving.model_dump() == before


def test_overlapping_coffee_table_cannot_be_merged_into_chair():
    chair = surface("chair", "chair", (0, 0.7, 0))
    chair.provenance = "primitive_fitted"
    chair.size = (1, 1, 1)
    coffee = surface("coffee", "coffee table", (0, 0.7, 0), semantic=True)
    survivors, merged = merge_furniture_surfaces([chair, coffee])
    assert len(survivors) == 2 and merged == {}
