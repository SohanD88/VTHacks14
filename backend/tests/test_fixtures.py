import cv2
import numpy as np
import pytest

from app.schemas import Geometry, Scene, SceneObject, Transform
from app.services.fixtures import refine_ceiling_lights, world_geometry


def setup_scene():
    x, z = np.meshgrid(np.linspace(-2, 2, 61), np.linspace(-7, -3, 61))
    ceiling = np.column_stack((x.ravel(), np.full(x.size, 3.0), z.ravel()))
    x, z = np.meshgrid(np.linspace(-0.2, 0.2, 15), np.linspace(-5.2, -4.8, 15))
    true = np.column_stack((x.ravel(), np.full(x.size, 3.0), z.ravel()))
    K = np.array([[100, 0, 100], [0, 100, 100], [0, 0, 1]])
    grid = np.arange(len(true)).reshape(15, 15)
    faces = np.stack((grid[:-1, :-1], grid[1:, :-1], grid[:-1, 1:]), axis=-1).reshape(-1, 3)
    views = []
    for frame, scale in enumerate([0.95, 1.0, 1.1]):
        pose = np.eye(4)
        pose[:3, :3] = np.diag([1, -1, -1])
        pose[:3, 3] = [frame * 0.1, 1.5, 0]
        camera = (true - pose[:3, 3]) @ pose[:3, :3]
        pixels = camera @ K.T
        pixels = np.rint(pixels[:, :2] / pixels[:, 2:]).astype(np.int32)
        mask = np.zeros((200, 200), np.uint8)
        cv2.fillConvexPoly(mask, cv2.convexHull(pixels), 1)
        points = pose[:3, 3] + (true - pose[:3, 3]) * scale
        views.append(
            dict(
                frame=frame,
                pose=pose,
                K=K,
                mask=mask.astype(bool),
                step=1,
                points=points,
                colors=np.ones_like(points),
                triangles=faces,
                score=0.9,
            )
        )
    observed = np.concatenate([v["points"] for v in views])

    def obj(id, kind, points):
        return SceneObject(
            id=id,
            label=id,
            kind=kind,
            confidence=0.9,
            position=(0, 0, 0),
            size=tuple(np.maximum(np.ptp(points, axis=0), 0.025)),
            geometry=Geometry(vertices=points.tolist(), colors=np.ones_like(points).tolist()),
            original_transform=Transform(),
            source_frames=[0, 1, 2],
        )

    return Scene(objects=[obj("ceiling", "ceiling", ceiling), obj("light", "light", observed)]), {
        "light": views
    }


def test_ceiling_fit_removes_depth_smear_preserving_raw_world_evidence():
    scene, views = setup_scene()
    before = world_geometry(scene.objects[1]).copy()
    result, report = refine_ceiling_lights(scene, views)
    light = result.objects[1]
    fitted = np.asarray(light.geometry.vertices) + light.position
    np.testing.assert_allclose(fitted[:, 1], 3.0, atol=1e-10)
    assert np.ptp(fitted[:, 2]) == pytest.approx(0.4)
    np.testing.assert_allclose(world_geometry(light), before, atol=1e-10)
    assert light.structural and not light.movable
    assert light.supporting_surface == "ceiling" and light.provenance == "primitive_fitted"
    assert light.original_transform.position == light.position
    assert len(report["fixtures"]) == 1 and report["fixtures"][0]["supporting_frames"] == [0, 1, 2]
    assert light.source_frames == [0, 1, 2]


@pytest.mark.parametrize(
    "failure",
    ["no_ceiling", "vertical", "unobserved", "mask_disagreement", "undersized_patch", "transient"],
)
def test_fixture_fit_abstains_without_geometric_and_multiview_support(failure):
    scene, views = setup_scene()
    if failure == "no_ceiling":
        scene.objects = scene.objects[1:]
    elif failure == "vertical":
        points = np.asarray(scene.objects[0].geometry.vertices)
        points[:, [0, 1]] = points[:, [1, 0]]
        scene.objects[0].geometry.vertices = [tuple(p) for p in points]
    elif failure == "unobserved":
        scene.objects[0].position = (20, 0, 0)
    elif failure == "mask_disagreement":
        for view in views["light"][1:]:
            view["mask"] = np.roll(view["mask"], 50, axis=1)
    elif failure == "undersized_patch":
        for view in views["light"]:
            view["mask"] = cv2.dilate(
                view["mask"].astype(np.uint8), np.ones((15, 15), np.uint8)
            ).astype(bool)
    elif failure == "transient":
        scene.objects[1].transient = True
    before = scene.model_dump()
    result, report = refine_ceiling_lights(scene, views)
    assert result.model_dump() == before
    assert report["fixtures"] == []


@pytest.mark.parametrize("covisible", [False, True])
def test_fixture_merging_requires_disjoint_observations_and_retains_raw_surfaces(covisible):
    scene, views = setup_scene()
    original = world_geometry(scene.objects[1]).copy()
    duplicate = scene.objects[1].model_copy(deep=True)
    duplicate.id = "duplicate"
    duplicate.source_frames = [0, 1, 2] if covisible else [3, 4, 5]
    scene.objects.append(duplicate)
    views[duplicate.id] = [
        dict(view, frame=frame) for view, frame in zip(views["light"], duplicate.source_frames)
    ]
    result, report = refine_ceiling_lights(scene, views)
    if covisible:
        assert len(result.objects) == 3 and report["merges"] == []
    else:
        assert len(result.objects) == 2 and len(report["merges"]) == 1
        light = result.objects[1]
        assert light.source_frames == [0, 1, 2, 3, 4, 5]
        np.testing.assert_allclose(
            world_geometry(light), np.vstack([original, original]), atol=1e-10
        )
        assert min(report["merges"][0]["reciprocal_mask_support"]) >= 0.55
