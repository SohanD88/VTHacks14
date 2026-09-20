"""Render review images from an exported prepared lounge model."""

import sys
from pathlib import Path

import bpy
from mathutils import Vector

out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(out / "model.blend"), load_ui=False)
s = bpy.context.scene
for root in s.objects:
    if root.get("spatial_cutaway"):
        for child in root.children_recursive:
            child.hide_render = True
s.render.engine = "CYCLES"
s.cycles.device = "CPU"
s.cycles.samples = 24
s.cycles.use_denoising = True
s.render.resolution_x = 1400
s.render.resolution_y = 1100
s.render.resolution_percentage = 100
s.render.image_settings.file_format = "PNG"
s.world = bpy.data.worlds.new("Demo daylight")
s.world.use_nodes = True
s.world.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.38, 0.43, 1)
s.world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
s.view_settings.view_transform = "AgX"
for loc, power, size in [((2, -5, 15), 2200, 10), ((-7, 5, 12), 2600, 10), ((5, 14, 10), 2000, 8)]:
    d = bpy.data.lights.new("Softbox", "AREA")
    d.energy = power
    d.shape = "DISK"
    d.size = size
    o = bpy.data.objects.new("Softbox", d)
    s.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector((0, 4, 0)) - o.location).to_track_quat("-Z", "Y").to_euler()
c = bpy.data.cameras.new("Demo camera")
o = bpy.data.objects.new("Demo camera", c)
s.collection.objects.link(o)
s.camera = o
c.type = "ORTHO"
c.ortho_scale = 23
c.clip_end = 200
for name, loc, target, scale in [
    ("overview", (17, -20, 23), (0, 3, 0), 23),
    ("plan", (0, 3, 30), (0, 3, 0), 26),
    ("lounge", (7, 3, 8), (0, 9.5, 1), 10),
]:
    o.location = loc
    o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()
    c.ortho_scale = scale
    s.render.filepath = str(out / (name + ".png"))
    bpy.ops.render.render(write_still=True)
