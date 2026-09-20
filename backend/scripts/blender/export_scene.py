"""Runs inside Blender. Export evaluated geometry and semantic objects without changing input."""

import json
import runpy
import uuid
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def kind_for(name):
    name = name.lower()
    for token, kind in [
        ("ceiling", "ceiling"),
        ("floor", "floor"),
        ("carpet", "floor"),
        ("lintel", "wall"),
        ("wall", "wall"),
        ("pier", "wall"),
        ("skirting", "wall"),
        ("elevator", "elevator"),
        ("door", "door"),
        ("entry", "door"),
        ("sofa", "sofa"),
        ("couch", "sofa"),
        ("table", "table"),
        ("chair", "chair"),
        ("light", "light"),
        ("window", "windowpane"),
    ]:
        if token in name:
            return kind
    return "fixture"


def export_room(input_path, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(input_path)
    if source.suffix.lower() == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    elif source.suffix.lower() == ".glb":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    else:
        raise ValueError("Expected .blend or .glb")
    original_scene = bpy.context.scene
    original_scene.view_layers[0].update()
    preview_direction = list(original_scene.get("spatial_preview_direction", [])) or None
    if original_scene.camera:
        view = original_scene.camera.matrix_world.to_quaternion() @ Vector((0, 0, 1))
        preview_direction = [float(view.x), float(view.z), float(-view.y)]
    # Evaluate in the original scene, preserving modifiers and generated geometry.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    hidden = {
        obj.name: bool(obj.hide_render or obj.hide_get() or obj.get("spatial_cutaway", False))
        for obj in original_scene.objects
    }
    groups = defaultdict(list)
    metadata = {}
    for obj in list(original_scene.objects):
        if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE"}:
            continue
        # Render helper meshes are omitted; architectural cutaway-hidden objects retained.
        if any(c.name == "Lighting" for c in obj.users_collection):
            continue
        parent = obj
        while parent.parent:
            parent = parent.parent
        group = str(obj.get("spatial_group", parent.get("spatial_label", parent.name)))
        col = next(
            (
                c.name
                for c in obj.users_collection
                if c.name in {"Elevators", "Double doors", "Entry door", "Light installation"}
            ),
            "",
        )
        if col and parent == obj and not obj.get("spatial_group"):
            group = col
            if col == "Elevators":
                group = (
                    " ".join(obj.name.split()[:2])
                    if obj.name.startswith("Elevator ") and obj.name.split()[1].isdigit()
                    else "Elevator controls"
                )
            if col == "Entry door" and ("wall" in obj.name.lower() or "lintel" in obj.name.lower()):
                group = obj.name
        part_metadata = {
            "id": parent.get("spatial_id"),
            "kind": obj.get("spatial_kind", parent.get("spatial_kind", kind_for(group))),
            "frames": list(obj.get("source_frames", parent.get("source_frames", []))),
            "hidden": hidden[obj.name] or bool(parent.get("spatial_cutaway", False)),
        }
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
        )
        if not mesh.vertices:
            bpy.data.meshes.remove(mesh)
            continue
        mesh.transform(obj.matrix_world)
        groups[group].append(dict(part_metadata, object=obj, mesh=mesh))
    partition = runpy.run_path(str(Path(__file__).with_name("export_groups.py")))["partition_group"]
    grouped = {}
    for name, parts in groups.items():
        for bucket in partition(parts):
            label = name + bucket["suffix"]
            metadata[label] = bucket
            grouped[label] = [(p["object"], p["mesh"]) for p in bucket["parts"]]
    groups = grouped
    scene = bpy.data.scenes.new("Sandbox export")
    if bpy.context.window:
        bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    if preview_direction:
        scene["spatial_preview_direction"] = preview_direction
    objects = []
    total_vertices = 0
    for group_name, parts in groups.items():
        corners = [v.co for _, mesh in parts for v in mesh.vertices]
        lo = Vector([min(p[i] for p in corners) for i in range(3)])
        hi = Vector([max(p[i] for p in corners) for i in range(3)])
        center = (lo + hi) / 2
        size = hi - lo
        sid = (
            metadata[group_name]["id"]
            or "blender-" + uuid.uuid5(uuid.NAMESPACE_URL, group_name).hex[:24]
        )
        root = bpy.data.objects.new(group_name, None)
        scene.collection.objects.link(root)
        root.location = center
        root["spatial_id"] = sid
        kind = str(metadata[group_name]["kind"])
        cutaway = (
            kind == "ceiling"
            or metadata[group_name]["hidden"]
            or all(hidden[o.name] for o, _ in parts)
        )
        root["spatial_label"] = group_name
        root["spatial_kind"] = kind
        root["spatial_cutaway"] = cutaway
        root["source_frames"] = metadata[group_name]["frames"]
        structural = kind in {"wall", "ceiling", "floor", "door", "elevator"}
        vertices, triangles, colors = [], [], []
        for original, mesh in parts:
            mesh.transform(Matrix.Translation(-center))
            child = bpy.data.objects.new(original.name, mesh)
            scene.collection.objects.link(child)
            child.parent = root
            child.hide_render = False
            child.hide_set(False)
            mesh.calc_loop_triangles()
            offset = len(vertices)
            vertices.extend((float(v.co.x), float(v.co.z), float(-v.co.y)) for v in mesh.vertices)
            triangles.extend(tuple(offset + i for i in t.vertices) for t in mesh.loop_triangles)
            colors.extend([(0.7, 0.7, 0.7)] * len(mesh.vertices))
        total_vertices += len(vertices)
        if total_vertices > 500000:
            raise ValueError("Model exceeds 500,000 vertices; simplify it before importing")
        pos = [center.x, center.z, -center.y]
        dims = [max(size.x, 0.001), max(size.z, 0.001), max(size.y, 0.001)]
        objects.append(
            dict(
                id=sid,
                label=group_name[:150],
                kind=kind[:80],
                confidence=1,
                asset_node=sid,
                position=pos,
                size=dims,
                cutaway_hidden=cutaway,
                geometry=dict(vertices=vertices, triangles=triangles, colors=colors),
                structural=structural,
                movable=not structural,
                editable=True,
                entrance=kind == "door",
                provenance="blender_generated",
                method="Blender evaluated mesh; imported layout, not reverified from video",
                original_transform=dict(position=pos),
                source_frames=metadata[group_name]["frames"],
            )
        )
    if not objects:
        raise ValueError("Blender scene contains no usable geometry")
    # Bake linked base-color shaders into a UV atlas. glTF cannot carry arbitrary shader nodes.
    bake_materials = {
        m
        for o in scene.objects
        if o.type == "MESH"
        for m in o.data.materials
        if m
        and m.use_nodes
        and any(
            n.type == "BSDF_PRINCIPLED"
            and n.inputs["Base Color"].is_linked
            and n.inputs["Base Color"].links[0].from_node.type != "TEX_IMAGE"
            for n in m.node_tree.nodes
        )
    }
    warnings = []
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8
    scene.cycles.device = "CPU"
    for material in bake_materials:
        meshes = [
            o for o in scene.objects if o.type == "MESH" and material.name in o.data.materials
        ]
        for o in scene.objects:
            o.select_set(False)
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.025)
        bpy.ops.object.mode_set(mode="OBJECT")
        image = bpy.data.images.new("Baked " + material.name, width=1024, height=1024)
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        material.node_tree.nodes.active = node
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_clear=False, margin=4)
        bs = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        for link in list(bs.inputs["Base Color"].links):
            material.node_tree.links.remove(link)
        material.node_tree.links.new(node.outputs["Color"], bs.inputs["Base Color"])
        image.pack()
        warnings.append("Baked procedural base color: " + material.name)
    for o in scene.objects:
        o.select_set(False)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "model.blend"), copy=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output / "model.glb"),
        export_format="GLB",
        use_active_scene=True,
        use_visible=False,
        export_apply=True,
        export_extras=True,
        export_yup=True,
        export_animations=False,
        export_cameras=False,
        export_lights=False,
    )
    result = dict(
        objects=objects,
        preview_direction=preview_direction,
        warnings=warnings,
        scale_note="Blender source dimensions; treated as estimated until measured.",
        unobserved="Imported model. Hidden or assumed surfaces are not verified observations.",
    )
    (output / "blender-scene.json").write_text(json.dumps(result))
    return dict(objects=len(objects), vertices=total_vertices, output=str(output))


if __name__ == "__main__":
    import sys

    args = sys.argv[sys.argv.index("--") + 1 :]
    export_room(args[0], args[1])
