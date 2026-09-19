import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.openings import refine_openings, world_geometry


def synthetic_opening():
    h, w, f = 400, 320, 300
    views = []
    for frame, x in enumerate([-0.06, 0, 0.06]):
        pose = np.eye(4)
        pose[:3, :3] = np.diag([1, -1, -1])
        pose[:3, 3] = [x, 1.5, 0]
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
        # A 2 m wide, 3 m high opening at z=-3; room surfaces lie behind it.
        left = round(w / 2 + (-1 - x) * f / 3)
        right = round(w / 2 + (1 - x) * f / 3)
        top = round(h / 2 - 1.5 * f / 3)
        rgb = np.full((h, w, 3), 190, np.uint8)
        rgb[top:, left:right] = 70
        depth = np.full((h, w), 3.0)
        depth[top:, left:right] = 7.0
        semantic = np.zeros((h, w), np.uint8)
        semantic[250:, left:right] = 3
        views.append(dict(frame=frame, rgb=rgb, depth=depth, semantic=semantic, pose=pose, K=K))
    y = np.linspace(0.2, 2.8, 50)
    points = np.c_[np.full(len(y), -1.0), y, np.full(len(y), -3.0)]
    door = SceneObject(
        id="door",
        kind="door",
        label="Opening candidate",
        confidence=0.8,
        position=(0, 0, 0),
        size=(0.1, 3, 0.1),
        geometry=Geometry(vertices=points.tolist(), colors=[[0.5] * 3] * len(points)),
        entrance=True,
        structural=True,
        movable=False,
        source_frames=[0, 1, 2],
        original_transform=Transform(),
    )
    floor = SceneObject(
        id="floor",
        kind="floor",
        label="Floor",
        confidence=0.9,
        position=(0, 0, 0),
        size=(4, 0.025, 6),
        structural=True,
        movable=False,
        geometry=Geometry(
            vertices=[[-2, 0, -3], [2, 0, -3], [2, 0, -9], [-2, 0, -9]],
            colors=[[0.5] * 3] * 4,
            triangles=[(0, 1, 2), (0, 2, 3)],
        ),
        original_transform=Transform(),
    )
    return Scene(objects=[door, floor]), views


@pytest.mark.parametrize("kind", ["door", "screen door"])
def test_opening_uses_observed_outline_preserves_raw_and_exports_open_geometry(kind):
    scene, views = synthetic_opening()
    scene.objects[0].kind = kind
    scene.objects[0].structural = False
    scene.objects[0].movable = True
    original = scene.objects[0].model_copy(deep=True)
    scene, report = refine_openings(scene, views, [3])
    assert len(report["openings"]) == 1
    fit = report["openings"][0]
    obj = scene.objects[0]
    assert fit["supporting_frames"] == [0, 1, 2]
    assert fit["clear_width"] == pytest.approx(2, abs=0.12)
    assert fit["clear_height"] == pytest.approx(3, abs=0.12)
    assert obj.provenance == "primitive_fitted" and obj.structural and not obj.movable
    assert obj.supporting_surface == "floor"
    assert np.allclose(world_geometry(obj), world_geometry(original))
    assert obj.observed_geometry.colors == original.geometry.colors
    assert obj.original_transform.position == obj.position
    points = (
        np.asarray(obj.geometry.vertices) @ Rotation.from_euler("xyz", obj.rotation).as_matrix().T
        + obj.position
    )
    assert points[:, 1].min() == pytest.approx(0, abs=1e-8)
    # The outline contains jambs/lintel, with no faces obstructing the passage.
    centers = np.asarray(obj.geometry.vertices)[np.asarray(obj.geometry.triangles)].mean(axis=1)
    assert not (
        (abs(centers[:, 0]) < fit["clear_width"] * 0.4)
        & (centers[:, 1] < fit["clear_height"] * 0.4)
    ).any()
    Scene.model_validate_json(scene.model_dump_json())


@pytest.mark.parametrize(
    "failure", ["single_view", "solid_door", "no_floor", "window", "unrelated_door"]
)
def test_unsupported_opening_does_not_replace_observed_geometry(failure):
    scene, views = synthetic_opening()
    if failure == "single_view":
        views = views[:1]
    if failure == "solid_door":
        for view in views:
            view["depth"][:] = 3
    if failure == "no_floor":
        scene.objects = scene.objects[:1]
    if failure == "window":
        for view in views:
            view["depth"][250:] = 3
            view["semantic"][:] = 0
    if failure == "unrelated_door":
        scene.objects[0].position = (8, 0, 0)
    original = scene.model_dump()
    after, report = refine_openings(scene, views, [3])
    assert not report["openings"]
    assert after.model_dump() == original
