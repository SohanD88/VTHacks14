"""Trusted wrapper for Gemini-authored geometry, run inside the Blender sandbox."""

import json
import runpy
from pathlib import Path

import bpy


def build_generated(source_path, output_dir):
    output = Path(output_dir)
    metadata = json.loads((output / "gemini-generation.json").read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    namespace = {"__name__": "__blender_scene__"}
    exec(compile(Path(source_path).read_text(), "gemini-scene.py", "exec"), namespace)
    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type in {"MESH", "CURVE", "FONT", "SURFACE"}]
    if not 1 <= len(meshes) <= 1500:
        raise ValueError("Generated scene must contain 1–1500 mesh objects")
    allowed = set(metadata["source_frames"])
    for obj in meshes:
        if not obj.get("source_frames"):
            obj["source_frames"] = metadata["source_frames"]
        if any(f not in allowed for f in obj["source_frames"]):
            raise ValueError("Generated object references a nonexistent source frame")
    scene["generator"] = metadata["model"]
    scene["assumptions"] = json.dumps(metadata["assumptions"])
    generated = output / "generated.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(generated))
    result = runpy.run_path(str(Path(__file__).with_name("export_scene.py")))["export_room"](
        str(generated), str(output)
    )
    details_path = output / "blender-scene.json"
    details = json.loads(details_path.read_text())
    details["warnings"].extend(metadata["assumptions"])
    details["warnings"].extend(metadata.get("frame_warnings", []))
    details["warnings"].append(
        "Gemini image-guided model; details and dimensions are approximations."
    )
    details["scale_note"] = "Gemini estimated proportions from video; not measured geometry."
    for obj in details["objects"]:
        obj["confidence"] = 0.7
        obj["method"] = metadata["model"] + " image-guided Blender geometry"
    details_path.write_text(json.dumps(details))
    if metadata.get("visual_review", True):
        try:
            runpy.run_path(str(Path(__file__).with_name("review_views.py")))["render_review_views"](
                str(output)
            )
        except Exception as exc:
            # A preview failure does not destroy a valid exported model.
            (output / "review-render-error.json").write_text(
                json.dumps({"error": type(exc).__name__})
            )
    return result
