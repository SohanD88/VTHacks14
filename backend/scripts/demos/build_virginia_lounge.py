"""Build the prepared IMG_1343 lounge demo with Blender (no vision API call).
Run: Blender --background --python this_file -- /absolute/output/directory
"""

import json
import math
import random
import runpy
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
import lounge_parts as p

OUT = Path(sys.argv[sys.argv.index("--") + 1])
OUT.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
p.palette()
random.seed(1343)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene["spatial_preview_direction"] = [0.8, 1.25, 1.4]
scene["generator"] = "Locally authored, footage-reviewed Blender demo"
H = 3.05


def floor(name, x0, x1, y0, y1, frames):
    p.group(name, "floor", frames)
    p.box(
        "Floor substrate", ((x0 + x1) / 2, (y0 + y1) / 2, -0.085), (x1 - x0, y1 - y0, 0.17), "wood3"
    )
    x = x0
    while x < x1 - 0.01:
        w = min(0.19, x1 - x)
        y = y0
        while y < y1 - 0.01:
            length = min(random.uniform(0.65, 1.75), y1 - y)
            mid = (x + w / 2, y + length / 2, 0.009)
            mi = random.randrange(12)
            p.box("Individual oak plank", mid, (w - 0.004, length - 0.005, 0.018), f"wood{mi}")
            # Long fine grain flecks retain detail in the browser without procedural shader baking.
            if random.random() < 0.55 and length > 0.25:
                p.box(
                    "Fine oak grain",
                    (mid[0] + random.uniform(-0.06, 0.06), mid[1], 0.019),
                    (0.005, length * 0.62, 0.001),
                    f"wood{max(0, mi - 3)}",
                )
            y += length
        x += w


def wall(name, a, b, height=H, material="ivory", hidden=False, frames=None):
    p.group(name, "wall", frames, hidden)
    a, b = Vector((*a, 0)), Vector((*b, 0))
    d = b - a
    p.box(
        "Plaster wall",
        (a + b) / 2 + Vector((0, 0, height / 2)),
        (d.length, 0.14, height),
        material,
        rz=math.atan2(d.y, d.x),
    )
    p.box(
        "Baseboard",
        (a + b) / 2 + Vector((0, 0, 0.08)),
        (d.length, 0.18, 0.16),
        "white",
        rz=math.atan2(d.y, d.x),
    )


def portal_wall(name, cx, y, frames):
    wall(name + " left", (cx - 1.15, y), (cx - 0.58, y), frames=frames)
    wall(name + " right", (cx + 0.58, y), (cx + 1.15, y), frames=frames)
    p.group(name + " lintel", "wall", frames, True)
    p.box("Above door", (cx, y, 2.7), (2.3, 0.15, 0.7), "white")


def artwork(name, x, y, z, angle=0, frames=None):
    p.group(name, "fixture", frames, True)
    before = set(scene.objects)
    p.box("Black picture frame", (0, 0, 0), (1.0, 0.045, 0.73), "black", 0.006)
    p.box("Cream mat", (0, -0.029, 0), (0.93, 0.008, 0.66), "paper")
    for i in range(12):
        p.box(
            "Graphic print",
            (random.uniform(-0.32, 0.32), -0.036, random.uniform(-0.24, 0.24)),
            (random.uniform(0.05, 0.16), 0.004, random.uniform(0.08, 0.27)),
            "sage",
        )
    for o in set(scene.objects) - before:
        o.location.z += z
    p.transform_since(before, x, y, angle)


# A near-end cross-passage connects the two main walkways, as clarified by the owner.
floor("West furnished walkway", -5, -1.55, 0, 8.3, [225, 300, 450, 600])
floor("East return walkway", 1.55, 5, 0, 8.3, [825, 900, 1050, 1125])
floor("Entry cross-passage — connects both walkways", -1.55, 1.55, 0, 2.05, [150, 225])
floor("Fireplace seating and turning area", -5, 5, 8.3, 12.0, [600, 675, 750, 825])
floor("Entrance approach corridor", -4.65, -2.35, -4.4, 0, [0, 75, 150])
floor("Exit approach corridor", 2.35, 4.65, -4.4, 0, [1125, 1200, 1350, 1425])
floor("Exit vestibule", 2.35, 4.65, -6, -4.4, [1490])
p.group("Front entrance carpet", "floor", [0])
p.box("Gray entrance mat", (-5.2, -3.5, 0.015), (1.1, 2.3, 0.03), "steel")
for i in range(12):
    p.box("Carpet stripe", (-5.2, -4.6 + i * 0.2, 0.032), (1.1, 0.012, 0.003), "sage")
# Open floor void has no floor mesh. Only observed railing edges are represented.
p.railing("West guardrail beside opening", (-1.55, 2.05), (-1.55, 8.3), [150, 600, 825])
p.railing("East guardrail beside opening", (1.55, 2.05), (1.55, 8.3), [825, 900, 975])
p.railing("Guardrail along entry cross-passage", (-1.55, 2.05), (1.55, 2.05), [150])
p.railing("Guardrail at fireplace turning area", (-1.55, 8.3), (1.55, 8.3), [825])
wall("West shelving wall", (-5.1, 0), (-5.1, 12), frames=[225, 300, 450])
wall("East paneled wall", (5.1, 0), (5.1, 12), hidden=True, frames=[975, 1125])
wall("East cutaway low wall", (5.1, 0), (5.1, 12), height=0.55, frames=[975, 1125])
wall("Back fireplace wall", (-5.1, 12), (5.1, 12), material="white", frames=[675, 750])
# Separate outer walls are hideable without hiding door assemblies.
for cx, name in [(-3.5, "Entrance"), (3.5, "Exit")]:
    frames = [0, 150] if cx < 0 else [1200, 1350]
    for side in [-1, 1]:
        spans = [(-4.4, -4.08), (-2.92, 0)] if cx < 0 and side < 0 else [(-4.4, 0)]
        for index, (start, end) in enumerate(spans):
            wall(
                f"{name} corridor {side:+d} wall {index}",
                (cx + side * 1.15, start),
                (cx + side * 1.15, end),
                hidden=True,
                frames=frames,
            )
            wall(
                f"{name} cutaway low wall {side:+d} {index}",
                (cx + side * 1.15, start),
                (cx + side * 1.15, end),
                height=0.65,
                frames=frames,
            )
            p.group(name + " corridor edge trim", "wall", frames)
            p.box(
                "Floor edge trim",
                (cx + side * 1.13, (start + end) / 2, 0.08),
                (0.045, end - start, 0.16),
                "white",
            )
    if cx < 0:
        wall(
            "Entrance closed corridor end", (-4.65, -4.4), (-2.35, -4.4), hidden=True, frames=frames
        )
        wall("Entrance end low wall", (-4.65, -4.4), (-2.35, -4.4), height=0.65, frames=frames)
        p.group("Entrance side doorway lintel", "wall", frames, True)
        p.box("Above relocated entrance", (-4.65, -3.5, 2.7), (0.15, 1.16, 0.7), "white")
        p.door(name + " glazed door", -4.65, -3.5, -math.pi / 2, frames=[0, 75])
    else:
        portal_wall(name + " doorway wall", cx, -4.4, [1425])
        p.door(name + " glazed door", cx, -4.4, frames=[1350, 1425])
    artwork(
        name + " corridor framed artwork",
        cx - 1.04,
        -2.1,
        1.6,
        -math.pi / 2,
        [150] if cx < 0 else [1350],
    )
wall("Vestibule outer wall east", (4.65, -6), (4.65, -4.4), hidden=True, frames=[1490])
wall("Vestibule outer wall west", (2.35, -6), (2.35, -4.4), hidden=True, frames=[1490])
p.group("Final exit double doors", "door", [1490])
for xx in [2.93, 4.07]:
    for sx in [-0.5, 0.5]:
        p.box("Double-door stile", (xx + sx * 0.96, -6, 1.1), (0.08, 0.07, 2.2), "white", 0.008)
    p.box("Double-door lower panel", (xx, -6, 0.55), (0.92, 0.075, 1.1), "white", 0.006)
    p.box("Double-door glazed pane", (xx, -6, 1.56), (0.84, 0.025, 0.88), "glass")
    p.box("Double-door top rail", (xx, -6, 2.16), (1.02, 0.085, 0.10), "white")
    p.rod("Panic push bar", (xx - 0.4, -5.92, 1.03), (xx + 0.4, -5.92, 1.03), 0.022, "steel")
# End return wall pieces and the observed white slatted treatment.
for x0, x1 in [(-5, -4.65), (-2.35, 2.35), (4.65, 5)]:
    wall("Front boundary " + str(x0), (x0, 0), (x1, 0), hidden=True, frames=[150, 1125])
for cx in [-3.5, 3.5]:
    p.group(
        ("Entry" if cx < 0 else "Exit") + " wall panel grooves",
        "wall",
        [150] if cx < 0 else [1425],
        True,
    )
    for side in [-1, 1]:
        for i in range(22):
            if cx < 0 and side < 0 and -4.08 < -4.3 + i * 0.20 < -2.92:
                continue
            p.box(
                "Vertical panel joint",
                (cx + side * 1.068, -4.3 + i * 0.20, 1.5),
                (0.006, 0.008, 2.85),
                "paper",
            )
# Charcoal columns frame the room without an invented solid central partition.
for i, (x, y) in enumerate(
    [(-1.7, 0.3), (1.7, 0.3), (-2.65, 8.65), (2.65, 8.65), (-4.8, 11.6), (4.8, 11.6)]
):
    p.group(f"Charcoal column {i + 1}", "wall", [225, 600, 825, 975])
    p.box("Column", (x, y, H / 2), (0.36, 0.44, H), "black", 0.014)
    p.box("Column base", (x, y, 0.065), (0.39, 0.47, 0.13), "black", 0.01)
    p.box("Electrical outlet", (x, y - 0.23, 0.42), (0.09, 0.013, 0.13), "white", 0.005)
# Long black and oak open shelving along the first walkway.
for bay in range(5):
    yy = 0.9 + bay * 1.4
    p.group(f"Open shelving bay {bay + 1}", "cabinet", [225, 300, 375, 450])
    p.box("Black writing desk", (-4.67, yy, 0.73), (0.72, 1.32, 0.055), "black", 0.012)
    for y in [yy - 0.65, yy + 0.65]:
        p.box("Shelving steel upright", (-4.34, y, 1.62), (0.035, 0.035, 2.85), "black")
        p.box("Desk side support", (-4.74, y, 0.36), (0.61, 0.045, 0.73), "black")
    for z in [1.43, 2.03, 2.63]:
        p.box("Natural oak shelf", (-4.70, yy, z), (0.59, 1.34, 0.055), "desk", 0.008)
        for j in range(random.randint(2, 5)):
            h = random.uniform(0.18, 0.30)
            p.box(
                "Shelf books",
                (-4.63, yy - 0.43 + j * 0.09, z + 0.04 + h / 2),
                (0.18, 0.06, h),
                random.choice(["paper", "redbook", "bluebook", "sage"]),
            )
    p.box("Monitor bezel", (-4.70, yy, 1.02), (0.055, 0.58, 0.34), "black", 0.012)
    p.box("Monitor display", (-4.667, yy, 1.02), (0.009, 0.52, 0.28), "screen")
    p.box("Monitor stand", (-4.66, yy, 0.80), (0.18, 0.21, 0.045), "steel")
    p.chair(f"Library desk chair {bay + 1}", -3.94, yy, -math.pi / 2, frames=[300, 375, 450])
    p.pot(f"Shelf plant {bay + 1}", -4.68, yy + 0.35, 2.66, 0.13, [300, 450])
# Shared worktables along the railed opening, with chairs and copper lights.
for side in [-1, 1]:
    for n, yy in enumerate([3.45, 6.55]):
        x = side * 2.07
        p.desk(
            ("West" if side < 0 else "East") + f" live-edge worktable {n + 1}",
            x,
            yy,
            2.65,
            math.pi / 2,
            [225, 600] if side < 0 else [975, 1050],
        )
        for j in [-0.82, 0, 0.82]:
            p.chair(
                ("West" if side < 0 else "East") + f" worktable chair {n + 1}-{j}",
                side * 2.65,
                yy + j,
                (-math.pi / 2 if side > 0 else math.pi / 2),
                material="black",
                frames=[600] if side < 0 else [1050],
            )
# Fireplace composition: rose paneling, inset flame ribbon and original words.
p.group("Rose fireplace feature wall", "wall", [675, 750])
p.box("Rose wall panel", (0, 11.87, 1.6), (5.45, 0.18, 2.85), "pinkwall", 0.006)
for i in range(11):
    p.box(
        "Rose vertical batten",
        (-2.62 + i * 0.524, 11.755, 1.6),
        (0.033, 0.045, 2.85),
        "pinktrim",
        0.006,
    )
p.group("Linear electric fireplace", "fixture", [675, 750])
p.box("Fireplace black recess", (0, 11.73, 0.50), (4.65, 0.045, 0.56), "black", 0.005)
p.box("Fireplace hearth", (0, 11.62, 0.235), (4.76, 0.31, 0.09), "black", 0.012)
for i in range(44):
    x = -2.2 + i * 0.10
    h = random.uniform(0.07, 0.20)
    p.sphere("Glowing ember", (x, 11.675, 0.28), (0.055, 0.025, 0.035), "warm_light")
    bpy.ops.mesh.primitive_cone_add(
        vertices=7, radius1=0.036, radius2=0, depth=h, location=(x, 11.69, 0.3 + h / 2)
    )
    p.finish(bpy.context.object, "Flame detail", "flame")
p.group("Virginia Made wall lettering", "fixture", [675, 750])
p.text(
    "VIRGINIA",
    "VIRGINIA",
    (-0.64, 11.73, 1.56),
    0.50,
    "white",
    rotation=(math.pi / 2, -math.pi / 2, 0),
)
p.text("MADE", "MADE", (0.67, 11.73, 1.80), 0.50, "white", rotation=(math.pi / 2, -math.pi / 2, 0))
p.group("Cross-pattern lounge rug", "floor", [675, 750, 825])
p.box("Woven cream rug", (0, 10.02, 0.032), (5.30, 3.48, 0.025), "rug", 0.01)
for ix in range(11):
    for iy in range(7):
        x = -2.4 + ix * 0.47
        y = 8.55 + iy * 0.47
        p.box("Rug cross", (x, y, 0.047), (0.17, 0.05, 0.002), "cross")
        p.box("Rug cross", (x, y, 0.048), (0.05, 0.17, 0.002), "cross")
p.sofa("Caramel leather lounge sofa", 0, 8.95, math.pi, [450, 525, 675, 825])
p.chair("Olive lounge chair west", -2.04, 10.35, math.pi / 2, True, frames=[675, 750])
p.chair("Olive lounge chair east", 2.04, 10.35, -math.pi / 2, True, frames=[750, 825])
p.round_table("Sage circular coffee table", -0.50, 10.26, 0.49, 0.40, "sage", [750])
p.round_table("Pale circular coffee table", 0.51, 10.59, 0.36, 0.48, "stone", [675, 750])
p.round_table("Black spool side table", -3.42, 7.9, 0.28, 0.44, "black", [450, 525])
p.group("Spool table rings", "table", [450, 525])
p.cyl("Spool ring top", (-3.42, 7.9, 0.48), 0.30, 0.04, "black", 24)
p.cyl("Spool ring bottom", (-3.42, 7.9, 0.09), 0.30, 0.04, "black", 24)
p.drum_chair("Dusty rose barrel chair west", -3.45, 9.25, -0.8, [450, 525])
p.drum_chair("Dusty rose barrel chair east", 3.45, 9.25, 0.8, [525, 825])
p.round_table("Barrel chairs side table", -3.75, 10.12, 0.3, 0.55, "stone", [450, 525])
p.pot("Terracotta lounge planter", 3.12, 8.15, 0, 0.29, [825])
# Windows at the far limit are retained; unseen space beyond this point is not filled in.
for side in [-1, 1]:
    p.group(("West" if side < 0 else "East") + " far window", "windowpane", [450, 600])
    cx = side * 3.92
    p.box("Night window", (cx, 11.86, 1.7), (2.03, 0.05, 2.42), "screen")
    for x in [cx - 0.96, cx, cx + 0.96]:
        p.box("Window mullion", (x, 11.78, 1.7), (0.045, 0.07, 2.48), "black")
    for z in [0.48, 1.7, 2.94]:
        p.box("Window horizontal", (cx, 11.78, z), (2.0, 0.07, 0.045), "black")
# Ceilings remain in the model and can be shown using the existing cutaway toggle.
for name, cx, cy, w, d in [
    ("West ceiling", -3.28, 4.15, 3.45, 8.3),
    ("East ceiling", 3.28, 4.15, 3.45, 8.3),
    ("Near cross-passage ceiling", 0, 1.02, 3.1, 2.05),
    ("Lounge ceiling", 0, 10.15, 10, 3.7),
    ("Entry hall ceiling", -3.5, -2.2, 2.3, 4.4),
    ("Exit hall ceiling", 3.5, -3, 2.3, 6),
]:
    p.group(name, "ceiling", [150, 300, 750, 1200], True)
    p.box("Ceiling plane", (cx, cy, H + 0.06), (w, d, 0.12), "white")
    for yy in [cy - d * 0.28, cy + d * 0.28]:
        p.cyl("Recessed light trim", (cx, yy, H - 0.01), 0.07, 0.025, "steel")
        p.cyl("Recessed light lens", (cx, yy, H - 0.025), 0.052, 0.007, "warm_light")
# Branch chandelier above the lounge, kept independently toggleable with the ceiling.
p.group("Branch chandelier", "light", [300, 450], True)
p.rod("Chandelier suspension", (0, 9.9, 3.0), (0, 9.9, 2.66), 0.016, "black")
for i in range(7):
    a = i * 2 * math.pi / 7
    end = (math.cos(a) * 1.03, 9.9 + math.sin(a) * 0.65, 2.70 + random.uniform(-0.08, 0.06))
    p.rod("Branch arm", (0, 9.9, 2.66), end, 0.02, "black")
    p.sphere("Opal globe", (end[0], end[1], end[2] - 0.08), (0.065, 0.065, 0.065), "warm_light")
# Readable but subtle wayfinding mounted at the observed door positions.
for name, x, y in [("ENTRANCE", -3.5, -4.30), ("EXIT", 3.5, -4.30)]:
    plaque_before = set(scene.objects)
    p.group(name + " identification plaque", "fixture", [0] if x < 0 else [1425])
    p.box("Door plaque", (x + 0.84, y, 1.63), (0.38, 0.025, 0.14), "black", 0.006)
    p.text("Plaque lettering", name, (x + 0.84, y - 0.018, 1.59), 0.055, "white")

    if x < 0:
        for obj in set(scene.objects) - plaque_before:
            local_x, local_y = obj.location.x + 3.5, obj.location.y + 4.4
            obj.location.x = -4.65 + local_y
            obj.location.y = -3.5 - local_x
            obj.rotation_euler.z -= math.pi / 2
print("Geometry assembled; joining semantic objects", flush=True)
# Join per semantic assembly after applying bevels. This keeps the browser scene lean.
assemblies = {}
for obj in list(scene.objects):
    if obj.type in {"MESH", "FONT", "CURVE"}:
        assemblies.setdefault(obj.get("spatial_group", obj.name), []).append(obj)
for name, objs in assemblies.items():
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    props = {
        k: objs[0][k] for k in ["spatial_group", "spatial_kind", "source_frames", "spatial_cutaway"]
    }
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.join()
    o = bpy.context.object
    o.name = name
    for k, v in props.items():
        o[k] = v
scene["assumptions"] = json.dumps(
    [
        "Video-guided prepared demo; geometry is authored and reviewed, "
        "not automatic photogrammetry.",
        "Glazed doors are depicted open, matching their use during the filmed walkthrough.",
        "3.5 ft (1.067 m) door-width assumption; all other dimensions visually estimated.",
        "Near-entry cross-passage connects both walkways, per user clarification.",
        "Entrance door relocated to the left corridor wall, per user correction.",
        "Space beyond the filmed fireplace turn and the lower level are not reconstructed.",
    ]
)
assumptions = json.loads(scene["assumptions"])
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "lounge.blend"))

exporter = Path(__file__).resolve().parents[1] / "blender" / "export_scene.py"
print(runpy.run_path(str(exporter))["export_room"](str(OUT / "lounge.blend"), str(OUT)), flush=True)
info = json.loads((OUT / "blender-scene.json").read_text())
info["warnings"] = assumptions
info["scale_note"] = (
    "Assumed 3.5 ft / 1.067 m entrance door width; other dimensions visually estimated."
)
info["unobserved"] = (
    "Prepared demo based on IMG_1343 2.MOV. The cross-passage is included; "
    "the railed opening and unfilmed areas have no invented floor."
)
for obj in info["objects"]:
    obj["confidence"] = 0.8
    obj["method"] = "Locally authored Blender geometry reviewed against IMG_1343 footage"
(OUT / "blender-scene.json").write_text(json.dumps(info))
print("DEMO BUILD COMPLETE", flush=True)
