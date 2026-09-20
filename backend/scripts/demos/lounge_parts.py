"""Reusable, locally authored Blender furnishings for the IMG_1343 demo.
All measurements are visual estimates, not a measured survey.
"""

import math
import random

import bpy
from mathutils import Vector

random.seed(1343)
M = {}
GROUP = "Architecture"
KIND = "fixture"
FRAMES = [0]
HIDDEN = False


def mat(name, color, rough=0.6, metallic=0, emission=0, alpha=1):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, alpha)
    m.use_nodes = True
    bs = m.node_tree.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (*color, alpha)
    bs.inputs["Roughness"].default_value = rough
    bs.inputs["Metallic"].default_value = metallic
    bs.inputs["Alpha"].default_value = alpha
    if emission:
        bs.inputs["Emission Color"].default_value = (*color, 1)
        bs.inputs["Emission Strength"].default_value = emission
    if alpha < 1:
        m.surface_render_method = "DITHERED"
    M[name] = m
    return m


def palette():
    colors = {
        "ivory": (0.82, 0.79, 0.70),
        "white": (0.9, 0.89, 0.83),
        "black": (0.022, 0.028, 0.027),
        "steel": (0.17, 0.19, 0.18),
        "gold": (0.48, 0.27, 0.075),
        "ochre": (0.53, 0.31, 0.09),
        "leather": (0.57, 0.36, 0.14),
        "cushion": (0.65, 0.44, 0.21),
        "seam": (0.39, 0.24, 0.10),
        "green": (0.21, 0.28, 0.18),
        "sage": (0.40, 0.44, 0.33),
        "mauve": (0.45, 0.36, 0.34),
        "pinkwall": (0.36, 0.17, 0.145),
        "pinktrim": (0.44, 0.23, 0.19),
        "rug": (0.77, 0.74, 0.66),
        "cross": (0.20, 0.23, 0.20),
        "stone": (0.69, 0.72, 0.65),
        "desk": (0.70, 0.59, 0.36),
        "terracotta": (0.52, 0.24, 0.12),
        "soil": (0.12, 0.075, 0.035),
        "leaf": (0.13, 0.27, 0.11),
        "paper": (0.72, 0.67, 0.53),
        "redbook": (0.36, 0.12, 0.09),
        "bluebook": (0.16, 0.25, 0.29),
    }
    for name, c in colors.items():
        mat(
            name,
            c,
            rough=0.42 if name in {"leather", "cushion", "green"} else 0.65,
            metallic=0.5 if name in {"steel", "gold"} else 0,
        )
    mat("glass", (0.34, 0.48, 0.51), rough=0.16, alpha=0.17)
    mat("warm_light", (1, 0.68, 0.26), emission=3)
    mat("flame", (1, 0.24, 0.015), emission=4)
    mat("screen", (0.035, 0.045, 0.05), rough=0.2)
    for i in range(12):
        t = i / 11
        mat(f"wood{i}", (0.49 + t * 0.19, 0.32 + t * 0.21, 0.15 + t * 0.17), rough=0.38)


def group(name, kind="fixture", frames=None, hidden=False):
    global GROUP, KIND, FRAMES, HIDDEN
    GROUP, KIND, FRAMES, HIDDEN = name, kind, frames or [0], hidden


def finish(o, name, material):
    o.name = name
    o["spatial_group"] = GROUP
    o["spatial_kind"] = KIND
    o["source_frames"] = FRAMES
    o["spatial_cutaway"] = HIDDEN
    if material:
        o.data.materials.append(M[material] if isinstance(material, str) else material)
    return o


def mesh_object(name, pos, vertices, faces, material):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(o)
    o.location = pos
    return finish(o, name, material)


def box(name, pos, size, material, bevel=0, rz=0):
    x, y, z = [v / 2 for v in size]
    vertices = [
        (-x, -y, -z),
        (x, -y, -z),
        (x, y, -z),
        (-x, y, -z),
        (-x, -y, z),
        (x, -y, z),
        (x, y, z),
        (-x, y, z),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    o = mesh_object(name, pos, vertices, faces, material)
    o.rotation_euler.z = rz
    if bevel:
        mod = o.modifiers.new("Soft edges", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        o.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return o


def cyl(name, pos, radius, depth, material, vertices=16):
    n = vertices
    v = [
        (radius * math.cos(i * 2 * math.pi / n), radius * math.sin(i * 2 * math.pi / n), z)
        for z in [-depth / 2, depth / 2]
        for i in range(n)
    ]
    faces = [tuple(reversed(range(n))), tuple(range(n, n * 2))]
    faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
    o = mesh_object(name, pos, v, faces, material)
    for poly in list(o.data.polygons)[2:]:
        poly.use_smooth = True
    return o


def rod(name, a, b, r, material):
    a, b = Vector(a), Vector(b)
    o = cyl(name, (a + b) / 2, r, (b - a).length, material, 10)
    o.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    return o


def sphere(name, pos, scale, material):
    n, m = 12, 6
    verts = []
    faces = []
    for j in range(m + 1):
        phi = math.pi * j / m
        for i in range(n):
            theta = 2 * math.pi * i / n
            verts.append(
                (
                    scale[0] * math.sin(phi) * math.cos(theta),
                    scale[1] * math.sin(phi) * math.sin(theta),
                    scale[2] * math.cos(phi),
                )
            )
    for j in range(m):
        for i in range(n):
            faces.append(
                ((j + 1) * n + i, (j + 1) * n + (i + 1) % n, j * n + (i + 1) % n, j * n + i)
            )
    o = mesh_object(name, pos, verts, faces, material)
    for poly in o.data.polygons:
        poly.use_smooth = True
    return o


def text(name, body, pos, size, material, rotation=(math.pi / 2, 0, 0), align="CENTER"):
    c = bpy.data.curves.new(name, "FONT")
    c.body = body
    c.size = size
    c.align_x = align
    c.extrude = 0.001
    o = bpy.data.objects.new(name, c)
    bpy.context.collection.objects.link(o)
    o.location = pos
    o.rotation_euler = rotation
    return finish(o, name, material)


def transform_since(before, x, y, angle):
    # Furniture constructors use local coordinates, then transform the whole assembly.
    c, s = math.cos(angle), math.sin(angle)
    for o in set(bpy.context.scene.objects) - before:
        a, b = o.location.x, o.location.y
        o.location.x = x + c * a - s * b
        o.location.y = y + s * a + c * b
        o.rotation_euler.z += angle


def chair(name, x, y, angle=0, lounge=False, material="green", frames=None):
    group(name, "chair", frames)
    before = set(bpy.context.scene.objects)
    w, d = (0.7, 0.68) if lounge else (0.46, 0.45)
    h = 0.43 if lounge else 0.47
    box("Upholstered seat", (0, 0, h), (w, d, 0.11), material, 0.045)
    back = box("Upholstered back", (0, d * 0.42, h + 0.28), (w, 0.09, 0.45), material, 0.035)
    back.rotation_euler.x = -0.12
    for a in [-1, 1]:
        xx = a * (w / 2 - 0.04)
        rod("Sled base", (xx, -d / 2, 0.055), (xx, d / 2, 0.055), 0.013, "black")
        rod("Front frame", (xx, -d / 2, 0.055), (xx, -d / 2, h), 0.013, "black")
        rod("Back frame", (xx, d / 2, 0.055), (xx, d / 2, h + 0.38), 0.013, "black")
        if lounge:
            rod("Arm rail", (xx, -d * 0.36, h + 0.19), (xx, d * 0.42, h + 0.26), 0.018, "black")
            rod("Front arm support", (xx, -d * 0.36, h), (xx, -d * 0.36, h + 0.19), 0.012, "black")
    if lounge:
        box("Back cushion seam", (0, d * 0.36, h + 0.28), (w * 0.92, 0.01, 0.012), "sage", 0.002)
    transform_since(before, x, y, angle)


def sofa(name, x, y, angle=0, frames=None):
    group(name, "sofa", frames)
    before = set(bpy.context.scene.objects)
    box("Lower upholstery", (0, 0, 0.31), (2.45, 0.92, 0.34), "leather", 0.09)
    for i in [-1, 0, 1]:
        box("Separate seat cushion", (i * 0.72, -0.10, 0.54), (0.70, 0.69, 0.19), "cushion", 0.065)
        back = box("Padded backrest", (i * 0.72, 0.32, 0.82), (0.73, 0.24, 0.58), "leather", 0.085)
        back.rotation_euler.x = -0.10
        box("Seat stitched piping", (i * 0.72, -0.445, 0.55), (0.66, 0.016, 0.016), "seam", 0.005)
    for a in [-1, 1]:
        box("Rounded sofa arm", (a * 1.16, 0, 0.69), (0.22, 0.96, 0.54), "leather", 0.085)
        for b in [-1, 1]:
            cyl("Sofa foot", (a * 0.99, b * 0.33, 0.10), 0.038, 0.20, "black")
    transform_since(before, x, y, angle)


def drum_chair(name, x, y, angle=0, frames=None):
    group(name, "chair", frames)
    before = set(bpy.context.scene.objects)
    cyl("Round cushioned seat", (0, 0, 0.48), 0.32, 0.18, "mauve", 24)
    # Curved padded back, opening toward -Y.
    verts = []
    faces = []
    for i in range(17):
        a = math.pi * i / 16
        for r, z in [(0.29, 0.5), (0.36, 0.5), (0.29, 0.98), (0.36, 0.98)]:
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for i in range(16):
        k = i * 4
        n = k + 4
        for a, b in [(0, 1), (0, 2), (1, 3), (2, 3)]:
            faces.append((k + a, k + b, n + b, n + a))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new("Curved barrel back", mesh)
    bpy.context.collection.objects.link(o)
    finish(o, "Curved barrel back", "mauve")
    for a in [-0.23, 0.23]:
        for b in [-0.23, 0.23]:
            rod("Slender brass leg", (a, b, 0.02), (a, b, 0.44), 0.018, "gold")
    transform_since(before, x, y, angle)


def round_table(name, x, y, r=0.4, h=0.46, material="sage", frames=None):
    group(name, "table", frames)
    cyl("Circular tabletop", (x, y, h), r, 0.055, material, 32)
    cyl("Pedestal", (x, y, h / 2), r * 0.43, h - 0.06, material, 24)


def desk(name, x, y, length=3.5, angle=0, frames=None):
    group(name, "table", frames)
    before = set(bpy.context.scene.objects)
    box("Thick oak tabletop", (0, 0, 0.77), (length, 0.86, 0.075), "desk", 0.035)
    # Restrained irregular dark streaks suggest the live-edge grain visible in the footage.
    for i in range(6):
        box(
            "Wood grain",
            (random.uniform(-length * 0.3, length * 0.3), random.uniform(-0.36, 0.36), 0.809),
            (random.uniform(0.3, length * 0.55), 0.012, 0.002),
            "wood1",
        )
    for x0 in [-length * 0.37, length * 0.37]:
        for y0 in [-0.33, 0.33]:
            rod("Table leg", (x0, y0, 0.02), (x0, y0, 0.74), 0.025, "black")
        rod("Under table brace", (x0, -0.33, 0.1), (x0, 0.33, 0.1), 0.024, "black")
    for x0 in [-length * 0.30, 0, length * 0.30]:
        cyl("Copper lamp stem", (x0, 0, 0.97), 0.028, 0.35, "gold")
        cyl("Copper lamp shade", (x0, 0, 1.15), 0.14, 0.09, "terracotta", 24)
        cyl("Lamp diffuser", (x0, 0, 1.10), 0.12, 0.01, "warm_light", 24)
    transform_since(before, x, y, angle)


def pot(name, x, y, z=0.0, r=0.18, frames=None):
    group(name, "plant", frames)
    bpy.ops.mesh.primitive_cone_add(
        vertices=16, radius1=r * 0.8, radius2=r, depth=r * 1.6, location=(x, y, z + r * 0.8)
    )
    finish(bpy.context.object, "Planter", "terracotta")
    cyl("Pot soil", (x, y, z + r * 1.6), r * 0.9, 0.025, "soil")
    for i in range(7):
        a = i * 2.4
        top = (
            x + math.cos(a) * r * 0.95,
            y + math.sin(a) * r * 0.95,
            z + r * (2.2 + random.random()),
        )
        rod("Plant stem", (x, y, z + r * 1.6), top, 0.006, "leaf")
        leaf = sphere("Leaf", top, (r * 0.45, r * 0.20, r * 0.7), "leaf")
        leaf.rotation_euler.y = 0.5


def railing(name, a, b, frames=None):
    group(name, "railing", frames)
    a, b = Vector((*a, 0)), Vector((*b, 0))
    delta = b - a
    length = delta.length
    for z in [0.12, 0.92, 1.04]:
        rod(
            "Guardrail",
            a + Vector((0, 0, z)),
            b + Vector((0, 0, z)),
            0.024 if z > 1 else 0.014,
            "black",
        )
    sections = max(1, round(length / 1.25))
    for i in range(sections + 1):
        p = a + delta * i / sections
        box("Railing upright", p + Vector((0, 0, 0.54)), (0.045, 0.045, 1.08), "black")
    # Wire-mesh infill: real gaps, not opaque panels.
    for i in range(1, int(length / 0.12)):
        p = a + delta * i / (length / 0.12)
        rod("Mesh vertical", p + Vector((0, 0, 0.15)), p + Vector((0, 0, 0.89)), 0.003, "steel")
    for z in [0.23, 0.35, 0.47, 0.59, 0.71, 0.83]:
        rod("Mesh horizontal", a + Vector((0, 0, z)), b + Vector((0, 0, z)), 0.003, "steel")


def door(name, x, y, angle=0, frames=None):
    group(name, "door", frames)
    before = set(bpy.context.scene.objects)
    w = 1.067
    h = 2.25
    for xx in [-w / 2, w / 2]:
        box("White door jamb", (xx, 0, h / 2), (0.085, 0.16, h + 0.12), "white", 0.008)
    box("Door header", (0, 0, h + 0.035), (w + 0.17, 0.16, 0.10), "white", 0.008)
    leaf_before = set(bpy.context.scene.objects)
    for xx in [-0.435, 0.435]:
        box("Glazed door stile", (xx, 0, h / 2), (0.14, 0.055, h), "white", 0.007)
    box("Lower kick rail", (0, 0, 0.20), (0.8, 0.055, 0.4), "white", 0.006)
    box("Upper door rail", (0, 0, 2.09), (0.8, 0.055, 0.31), "white", 0.006)
    box("Clear door glazing", (0, 0, 1.2), (0.74, 0.018, 1.60), "glass")
    cyl("Handle rose", (0.41, -0.055, 1.0), 0.046, 0.022, "steel").rotation_euler.x = math.pi / 2
    rod("Lever handle", (0.41, -0.085, 1.0), (0.27, -0.085, 1.0), 0.017, "steel")
    box("Door closer", (0.17, -0.07, 2.18), (0.32, 0.065, 0.06), "steel", 0.008)
    for zz in [0.28, 1.13, 1.99]:
        cyl("Hinge", (-0.49, 0, zz), 0.018, 0.10, "steel", 12)
    # Both glazed leaves are opened during the filmed traversal.
    for obj in set(bpy.context.scene.objects) - leaf_before:
        a, b = obj.location.x + 0.49, obj.location.y
        opening = math.radians(78)
        obj.location.x = -0.49 + a * math.cos(opening) - b * math.sin(opening)
        obj.location.y = a * math.sin(opening) + b * math.cos(opening)
        obj.rotation_euler.z += opening
    transform_since(before, x, y, angle)
