"""Deterministic room geometry from validated room-plan data; run only inside Blender."""

import json
import math
import runpy
from pathlib import Path

import bpy


def build_and_export(plan_path, output_dir):
    plan = json.loads(Path(plan_path).read_text())
    # Backend validates the plan before executing this script.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Video room approximation"
    materials = {}
    for name, color in [
        ("wall", (0.72, 0.73, 0.70)),
        ("floor", (0.38, 0.27, 0.16)),
        ("ceiling", (0.85, 0.85, 0.82)),
        ("sofa", (0.18, 0.28, 0.34)),
        ("table", (0.36, 0.20, 0.09)),
        ("chair", (0.25, 0.27, 0.29)),
        ("cabinet", (0.40, 0.35, 0.28)),
        ("elevator", (0.43, 0.47, 0.49)),
        ("light", (0.9, 0.86, 0.65)),
        ("door", (0.62, 0.50, 0.35)),
    ]:
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*color, 1)
        m.use_nodes = True
        bs = m.node_tree.nodes.get("Principled BSDF")
        bs.inputs["Base Color"].default_value = (*color, 1)
        bs.inputs["Roughness"].default_value = 0.65
        materials[name] = m

    def box(label, center, size, kind, group, frames=None, rotation=0):
        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        o = bpy.context.object
        o.name = label
        o.dimensions = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        o.rotation_euler.z = rotation
        o.data.materials.append(materials[kind])
        o["spatial_cutaway"] = group.startswith("front ") or kind == "ceiling"
        o["spatial_group"] = group
        o["spatial_kind"] = kind
        o["source_frames"] = frames or []
        bevel = o.modifiers.new("Edges", "BEVEL")
        bevel.width = 0.015
        bevel.segments = 2
        return o

    w, d, h = plan["width"], plan["depth"], plan["height"]
    box("Floor", (0, 0, -0.08), (w, d, 0.16), "floor", "Floor")
    if plan["ceiling"]:
        box("Ceiling", (0, 0, h + 0.06), (w, d, 0.12), "ceiling", "Ceiling")
    for side in plan["walls"]:
        horizontal = side in ("front", "back")
        span = w if horizontal else d
        fixed = (-1 if side in ("front", "left") else 1) * (d if horizontal else w) / 2

        def segment(label, lo, hi, zlo, zhi, kind="wall", group=None, frames=None):
            if hi - lo < 0.001 or zhi - zlo < 0.001:
                return
            center = (
                ((lo + hi) / 2, fixed, (zlo + zhi) / 2)
                if horizontal
                else (fixed, (lo + hi) / 2, (zlo + zhi) / 2)
            )
            size = (hi - lo, 0.12, zhi - zlo) if horizontal else (0.12, hi - lo, zhi - zlo)
            box(label, center, size, kind, group or f"{side} wall", frames)

        openings = sorted(
            [x for x in plan["doors"] if x["wall"] == side], key=lambda x: x["offset"]
        )
        cursor = -span / 2
        for i, door in enumerate(openings):
            lo = door["offset"] - door["width"] / 2
            hi = door["offset"] + door["width"] / 2
            dh = door["height"]
            segment(side + " wall", cursor, lo, 0, h)
            segment(side + " lintel", lo, hi, dh, h)
            group = f"{side} doorway {i + 1}"
            segment(
                group + " left jamb", lo, lo + 0.05, 0, dh, "door", group, door["source_frames"]
            )
            segment(
                group + " right jamb", hi - 0.05, hi, 0, dh, "door", group, door["source_frames"]
            )
            segment(group + " header", lo, hi, dh - 0.05, dh, "door", group, door["source_frames"])
            cursor = hi
        segment(side + " wall", cursor, span / 2, 0, h)
    for i, item in enumerate(plan["furniture"]):
        kind = item["kind"]
        fw, fd, fh = item["width"], item["depth"], item["height"]
        label = f"{item['label']} {i + 1}"
        angle = math.radians(item["rotation_degrees"])

        def part(suffix, x, y, z, sx, sy, sz):
            px = item["x"] + x * math.cos(angle) - y * math.sin(angle)
            py = item["y"] + x * math.sin(angle) + y * math.cos(angle)
            box(
                label + " " + suffix,
                (px, py, z),
                (sx, sy, sz),
                kind,
                label,
                item["source_frames"],
                angle,
            )

        if kind in ("table", "chair"):
            top = fh if kind == "table" else fh * 0.5
            part("top", 0, 0, top - 0.04, fw, fd, 0.08)
            for x in (-fw * 0.4, fw * 0.4):
                for y in (-fd * 0.4, fd * 0.4):
                    part("leg", x, y, (top - 0.08) / 2, 0.06, 0.06, max(0.03, top - 0.08))
            if kind == "chair":
                part("back", 0, fd * 0.45, fh * 0.75, fw, 0.08, fh * 0.5)
        elif kind == "sofa":
            part("base", 0, 0, fh * 0.25, fw, fd, fh * 0.4)
            part("back", 0, fd * 0.4, fh * 0.65, fw, fd * 0.2, fh * 0.7)
            for x in (-fw * 0.45, fw * 0.45):
                part("arm", x, 0, fh * 0.48, fw * 0.1, fd, fh * 0.5)
            for x in (-fw * 0.22, fw * 0.22):
                part("cushion", x, -fd * 0.05, fh * 0.48, fw * 0.4, fd * 0.7, fh * 0.12)
        else:
            part("body", 0, 0, fh / 2, fw, fd, fh)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = output / "generated.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    module = runpy.run_path(str(Path(__file__).with_name("export_scene.py")))
    result = module["export_room"](str(source), str(output))
    details = json.loads((output / "blender-scene.json").read_text())
    details["warnings"].extend(plan["assumptions"])
    details["scale_note"] = (
        "Approximate video-guided layout; dimensions are inferred, not measured."
    )
    for obj in details["objects"]:
        obj["method"] = "Video-guided structured room plan + Blender procedural geometry"
        obj["confidence"] = 0.7
    (output / "blender-scene.json").write_text(json.dumps(details))
    return result
