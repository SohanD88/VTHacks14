import numpy as np
from scipy.spatial.transform import Rotation

from app.schemas import Geometry, ScaleCalibration, Scene, SceneObject, Transform
from app.services.calibration import apply_calibration, validate_edit


def world(obj, geometry):
    return (
        np.asarray(geometry.vertices)
        * obj.scale
        @ Rotation.from_euler("xyz", obj.rotation).as_matrix().T
        + obj.position
    )


def test_uniform_scaling_preserves_raw_geometry_orientation_edits_and_camera_registration():
    geom = Geometry(vertices=[(1, 2, 3), (-2, 1, 3)], colors=[(1, 1, 1)] * 2)
    obj = SceneObject(
        id="object",
        label="Object",
        kind="chair",
        confidence=0.8,
        position=(2, 1, -3),
        size=(3, 1, 1),
        rotation=(0, 0.7, 0),
        scale=(1, 2, 1),
        geometry=geom,
        observed_geometry=geom.model_copy(deep=True),
        original_transform=Transform(position=(2, 1, -3), rotation=(0, 0.7, 0), scale=(1, 2, 1)),
    )
    original = Scene(objects=[obj], camera_path=[(1, 2, 3), (3, 2, 1)], camera_frames=[2, 7])
    edited = original.model_copy(deep=True)
    edited.objects[0].position = (3, 1, -3)
    ref = ScaleCalibration(reference_points=((0, 0, 0), (1, 0, 0)), distance_m=1.0668)
    scaled = apply_calibration(edited, ref, original)
    validate_edit(original, scaled)
    np.testing.assert_allclose(
        world(scaled.objects[0], scaled.objects[0].geometry),
        world(edited.objects[0], geom) * 1.0668,
    )
    np.testing.assert_allclose(
        world(scaled.objects[0], scaled.objects[0].observed_geometry),
        world(edited.objects[0], geom) * 1.0668,
    )
    np.testing.assert_allclose(scaled.camera_path, np.asarray(original.camera_path) * 1.0668)
    assert scaled.objects[0].modified
    assert scaled.objects[0].geometry == original.objects[0].geometry
    restored = apply_calibration(scaled, None, original)
    validate_edit(original, restored)
    np.testing.assert_allclose(restored.objects[0].position, edited.objects[0].position)
    np.testing.assert_allclose(restored.objects[0].scale, edited.objects[0].scale)
    assert restored.camera_path == original.camera_path
    assert restored.calibration is None and restored.objects[0].modified
