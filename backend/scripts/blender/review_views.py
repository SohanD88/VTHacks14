"""Render exported geometry for visual review, without altering saved GLB/blend artifacts."""

from pathlib import Path

import bpy
from mathutils import Vector


def render_review_views(output_dir):
    output = Path(output_dir)
    scene = bpy.context.scene
    roots = [o for o in scene.objects if o.get("spatial_id")]
    corners = [
        o.matrix_world @ Vector(c) for o in scene.objects if o.type == "MESH" for c in o.bound_box
    ]
    if not corners:
        raise ValueError("No geometry to review")
    low = Vector([min(v[i] for v in corners) for i in range(3)])
    high = Vector([max(v[i] for v in corners) for i in range(3)])
    center = (low + high) / 2
    span = max((high - low).length, 1)
    hidden = {}
    for root in roots:
        for child in root.children_recursive:
            hidden[child] = child.hide_render
            if root.get("spatial_cutaway"):
                child.hide_render = True
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("Review world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs["Color"].default_value = (0.3, 0.3, 0.3, 1)
    scene.world.node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.7
    scene.view_settings.view_transform = "AgX"
    camera = bpy.data.objects.new("Review camera", bpy.data.cameras.new("Review camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = span * 1.08
    camera.data.clip_end = max(200, span * 10)
    lights = []
    for direction in [(1, -1, 2), (-1, 1, 2)]:
        data = bpy.data.lights.new("Review softbox", "AREA")
        data.energy = 15 * span * span
        data.shape = "DISK"
        data.size = span
        light = bpy.data.objects.new("Review softbox", data)
        scene.collection.objects.link(light)
        light.location = center + Vector(direction).normalized() * span
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        lights.append(light)
    # Consistent independent viewpoints, not an invented camera calibration.
    directions = [(0.5, -1, 0.65), (-0.7, -1, 0.55), (0.05, -0.1, 1.5)]
    try:
        for index, direction in enumerate(directions):
            camera.location = center + Vector(direction).normalized() * span * 2
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(output / f"review-view-{index}.png")
            bpy.ops.render.render(write_still=True)
    finally:
        for child, value in hidden.items():
            child.hide_render = value
        for obj in [camera, *lights]:
            bpy.data.objects.remove(obj, do_unlink=True)
