"""Uniform room scaling without rewriting observed geometry or reconstruction evidence."""

from math import isclose

from app.schemas import ScaleCalibration, Scene


def factor(scene: Scene) -> float:
    return scene.calibration.factor if scene.calibration else 1.0


def apply_calibration(scene: Scene, reference: ScaleCalibration | None, original: Scene) -> Scene:
    result = scene.model_copy(deep=True)
    target = reference.factor if reference else 1.0
    ratio = target / factor(scene)
    for obj in result.objects:
        obj.position = tuple(value * ratio for value in obj.position)
        obj.scale = tuple(value * ratio for value in obj.scale)
    result.camera_path = [tuple(value * target for value in p) for p in original.camera_path]
    result.calibration = reference
    result.scale_note = (
        f"Estimated dimensions scaled using a user-{reference.basis} "
        f"{reference.distance_m:.4f} m reference. Uniform scale only; local distortion remains."
        if reference
        else original.scale_note
    )
    # Assignment validation is not enabled on mutable contracts; revalidate all bounds.
    return Scene.model_validate(result.model_dump())


def same_transform(a, b):
    return a.deleted == b.deleted and all(
        isclose(x, y, rel_tol=1e-10, abs_tol=1e-10)
        for field in ("position", "rotation", "scale")
        for x, y in zip(getattr(a, field), getattr(b, field))
    )


def validate_edit(original: Scene, scene: Scene):
    """Calibration may change coordinates, never IDs, geometry or semantic provenance."""
    if original.calibration is not None:
        raise ValueError("Original reconstruction must retain its uncalibrated coordinates")
    baseline = apply_calibration(original, scene.calibration, original)
    originals = {o.id: o for o in baseline.objects}
    if set(originals) != {o.id for o in scene.objects}:
        raise ValueError("Preserve object IDs; use the deleted flag to hide an object.")
    mutable = {"position", "rotation", "scale", "modified", "deleted"}
    for obj in scene.objects:
        base = originals[obj.id]
        if obj.model_dump(exclude=mutable) != base.model_dump(exclude=mutable):
            raise ValueError("Only transforms, deletion and room scale may be edited.")
        obj.modified = not same_transform(obj, base)
    if scene.model_dump(exclude={"objects"}) != baseline.model_dump(exclude={"objects"}):
        raise ValueError("Camera path and reconstruction provenance must be preserved.")
