"""Bounded, self-contained GLB validation; never fetch external asset references."""

import base64
import hashlib
import json
import struct
from functools import lru_cache

MAX_GLB = 16_000_000


@lru_cache(maxsize=4)
def document(data):
    try:
        raw = base64.b64decode(data, validate=True)
        if not 20 <= len(raw) <= MAX_GLB:
            raise ValueError("GLB must be smaller than 16 MB")
        magic, version, length = struct.unpack_from("<4sII", raw)
        if magic != b"glTF" or version != 2 or length != len(raw):
            raise ValueError("Invalid GLB header")
        length, kind = struct.unpack_from("<II", raw, 12)
        if kind != 0x4E4F534A or length > len(raw) - 20:
            raise ValueError("Invalid GLB JSON chunk")
        doc = json.loads(raw[20 : 20 + length])
        if doc.get("asset", {}).get("version") != "2.0":
            raise ValueError("Expected glTF 2.0")
        for key in ("nodes", "buffers", "images", "meshes", "bufferViews", "accessors"):
            items = doc.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("Invalid GLB collection")
        nodes = doc.get("nodes", [])
        for node in nodes:
            if not isinstance(node.get("extras", {}), dict):
                raise ValueError("Invalid GLB node metadata")
            children = node.get("children", [])
            if not isinstance(children, list) or any(
                type(child) is not int or not 0 <= child < len(nodes) for child in children
            ):
                raise ValueError("Invalid GLB child reference")
        # Reject cycles and multiply parented nodes before handing the graph to Three.js.
        parents = set()
        for node in nodes:
            for child in node.get("children", []):
                if child in parents:
                    raise ValueError("GLB node has multiple parents")
                parents.add(child)
        visited = set()
        pending = [i for i in range(len(nodes)) if i not in parents]
        while pending:
            current = pending.pop()
            visited.add(current)
            pending.extend(nodes[current].get("children", []))
        if len(visited) != len(nodes):
            raise ValueError("Cyclic GLB node hierarchy")
        if len(nodes) > 5000:
            raise ValueError("Too many GLB nodes")
        for item in doc.get("buffers", []) + doc.get("images", []):
            if "uri" in item:
                raise ValueError("GLB must embed every buffer and texture")
        if doc.get("animations") or doc.get("skins"):
            raise ValueError("Export a static room model without animation or skinning")
        return doc
    except (AttributeError, TypeError, KeyError, struct.error, json.JSONDecodeError) as exc:
        raise ValueError("Invalid GLB model") from exc


def validate_asset(data, digest):
    document(data)
    if hashlib.sha256(base64.b64decode(data)).hexdigest() != digest:
        raise ValueError("GLB checksum mismatch")


def asset_node_ids(data):
    ids = [n.get("extras", {}).get("spatial_id") for n in document(data).get("nodes", [])]
    ids = [i for i in ids if i is not None]
    if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("GLB node IDs must be unique strings")
    return set(ids)
