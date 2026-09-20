"""Estimated, single-level routes over the current rendered scene's floor geometry.

This is model-space collision checking, not observed free-space reconstruction. Hidden
and low-confidence objects still block paths; deleted objects do not. Door labels never
cut holes in walls or establish building exits.
"""

from dataclasses import dataclass
from math import cos, dist, sin
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
from scipy.ndimage import distance_transform_edt, label

from app.routing.graph import BuildingGraph, GraphEdge, GraphNode, Target
from app.routing.mission import Mission, Objective
from app.routing.planner import plan
from app.schemas import Contract, Scene, SceneObject, Vector3

CELL = 0.15
MAX_CELLS = 20_000
MAX_TRIANGLES = 120_000
OPENINGS = {"door", "doorway", "entrance", "exit", "opening"}


class AdapterError(ValueError):
    pass


class RouteEndpoint(Contract):
    point: Vector3 | None = None
    object_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.point is None) == (self.object_id is None):
            raise ValueError("Supply either a floor point or a doorway object_id")
        return self


class SceneRouteRequest(Contract):
    revision: int = Field(ge=0)
    start: RouteEndpoint
    end: RouteEndpoint
    clearance_m: float = Field(default=0.2, ge=0.1, le=0.6)


class ResolvedEndpoint(Contract):
    point: Vector3
    label: str
    object_id: str | None = None


class SceneRouteResponse(Contract):
    scan_id: str
    revision: int
    polyline: list[Vector3]
    distance_m: float
    start: ResolvedEndpoint
    end: ResolvedEndpoint
    estimated: Literal[True] = True
    warnings: list[str]
    clearance_m: float
    cell_size: float


@dataclass
class Mesh:
    obj: SceneObject
    vertices: np.ndarray
    faces: np.ndarray


def world_vertices(obj: SceneObject) -> np.ndarray:
    """Match Three.js Euler XYZ, then scale/rotate/translate local geometry."""
    x, y, z = obj.rotation
    rx = np.array([[1, 0, 0], [0, cos(x), -sin(x)], [0, sin(x), cos(x)]])
    ry = np.array([[cos(y), 0, sin(y)], [0, 1, 0], [-sin(y), 0, cos(y)]])
    rz = np.array([[cos(z), -sin(z), 0], [sin(z), cos(z), 0], [0, 0, 1]])
    vertices = np.asarray(obj.geometry.vertices, dtype=float).reshape(-1, 3)
    if not len(vertices):
        vertices = (
            np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)])
            * obj.size
        )
    return (vertices * obj.scale) @ (rx @ ry @ rz).T + obj.position


def _clip_height(polygon: np.ndarray, height: float, above: bool) -> np.ndarray:
    result = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        inside_a = a[1] >= height if above else a[1] <= height
        inside_b = b[1] >= height if above else b[1] <= height
        if inside_a:
            result.append(a)
        if inside_a != inside_b:
            result.append(a + (b - a) * ((height - a[1]) / (b[1] - a[1])))
    return np.asarray(result).reshape(-1, 3)


def _contains(points: np.ndarray, polygon: np.ndarray, margin: float = 0) -> np.ndarray:
    """Convex polygon containment plus distance to its edges, including line projections."""
    positive = np.ones(len(points), dtype=bool)
    negative = positive.copy()
    near = np.zeros(len(points), dtype=bool)
    area = 0.0
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        ab = b - a
        delta = points - a
        cross = ab[0] * delta[:, 1] - ab[1] * delta[:, 0]
        positive &= cross >= -1e-9
        negative &= cross <= 1e-9
        area += a[0] * b[1] - a[1] * b[0]
        length2 = float(ab @ ab)
        t = np.clip(delta @ ab / length2, 0, 1) if length2 > 1e-15 else np.zeros(len(points))
        near |= np.sum((delta - t[:, None] * ab) ** 2, axis=1) <= margin**2 + 1e-12
    return near | ((positive | negative) if abs(area) > 1e-10 else False)


def _endpoint(endpoint: RouteEndpoint, meshes: list[Mesh]) -> tuple[np.ndarray, str]:
    if endpoint.point is not None:
        return np.asarray(endpoint.point), "Floor point"
    mesh = next((m for m in meshes if m.obj.id == endpoint.object_id), None)
    if mesh is None:
        raise AdapterError("The selected doorway no longer exists in this scene.")
    if not (mesh.obj.entrance or mesh.obj.kind.lower() in OPENINGS):
        raise AdapterError("Choose a floor point or a doorway, rather than furniture or a wall.")
    point = (mesh.vertices.min(axis=0) + mesh.vertices.max(axis=0)) / 2
    point[1] = mesh.vertices[:, 1].min()
    return point, mesh.obj.label


def route_scene(scene: Scene, request: SceneRouteRequest, scan_id: str) -> dict:
    meshes = [
        Mesh(o, world_vertices(o), np.asarray(o.geometry.triangles, dtype=int).reshape(-1, 3))
        for o in scene.objects
        if not o.deleted
    ]
    if sum(len(m.faces) for m in meshes) > MAX_TRIANGLES:
        raise AdapterError("This model is too detailed for routing. Simplify it before planning.")
    start_point, start_label = _endpoint(request.start, meshes)
    end_point, end_label = _endpoint(request.end, meshes)
    floors = []
    for mesh in meshes:
        if mesh.obj.kind.lower() != "floor":
            continue
        for triangle in mesh.vertices[mesh.faces]:
            normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
            length = np.linalg.norm(normal)
            if length > 1e-9 and abs(normal[1]) / length > 0.995:
                floors.append(triangle)
    if not floors:
        raise AdapterError("No usable floor mesh was found. Routing needs a modeled floor surface.")
    heights = np.array([t[:, 1].mean() for t in floors])
    start_height = heights[np.argmin(abs(heights - start_point[1]))]
    end_height = heights[np.argmin(abs(heights - end_point[1]))]
    if abs(start_point[1] - start_height) > 0.35 or abs(end_point[1] - end_height) > 0.35:
        raise AdapterError("Choose points on the floor, or select a doorway from the list.")
    if abs(start_height - end_height) > 0.15:
        raise AdapterError("Choose points on the same floor. Stair connections are not mapped yet.")
    floor_mesh = [t for t, h in zip(floors, heights) if abs(h - start_height) <= 0.15]
    elevation = max(t[:, 1].max() for t in floor_mesh)
    bounds = np.concatenate(floor_mesh)[:, [0, 2]]
    origin = np.floor(bounds.min(axis=0) / CELL) * CELL
    width, depth = np.ceil((bounds.max(axis=0) - origin) / CELL).astype(int)
    if width <= 0 or depth <= 0 or width * depth > MAX_CELLS:
        raise AdapterError("Floor area exceeds the routing grid limit. Use a smaller room model.")
    xx, zz = np.meshgrid(np.arange(width), np.arange(depth))
    centers = origin + (np.column_stack((xx.ravel(), zz.ravel())) + 0.5) * CELL
    samples = np.array([(x, z) for x in (-0.49, 0, 0.49) for z in (-0.49, 0, 0.49)]) * CELL
    supported = np.zeros((len(centers), len(samples)), dtype=bool)
    occupied = np.zeros(len(centers), dtype=bool)
    work = 0

    def candidates(poly, margin):
        nonlocal work
        lo = np.maximum(0, np.floor((poly.min(axis=0) - margin - origin) / CELL).astype(int))
        hi = np.minimum(
            (width - 1, depth - 1),
            np.floor((poly.max(axis=0) + margin - origin) / CELL).astype(int),
        )
        x, z = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        ids = (z * width + x).ravel()
        work += len(ids) * 9
        if work > 25_000_000:
            raise AdapterError("Geometry is too complex for routing. Simplify the room model.")
        return ids

    for triangle in floor_mesh:
        polygon = triangle[:, [0, 2]]
        ids = candidates(polygon, CELL)
        points = (centers[ids, None] + samples).reshape(-1, 2)
        supported[ids] |= _contains(points, polygon).reshape(-1, len(samples))
    # The bounding circle of each grid cell makes rasterized obstacles conservative.
    cell_radius = CELL / 2**0.5
    band_low, band_high = elevation + 0.08, elevation + 1.8
    for mesh in meshes:
        lo, hi = mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)
        if hi[1] < band_low or lo[1] > band_high:
            continue
        if mesh.obj.kind.lower() not in {"wall", "floor", "ceiling", *OPENINGS} or not len(
            mesh.faces
        ):
            # Furniture and point clouds use conservative bounds, not hollow interiors.
            polygons = [np.array([(lo[0], lo[2]), (hi[0], lo[2]), (hi[0], hi[2]), (lo[0], hi[2])])]
        else:
            polygons = []
            for triangle in mesh.vertices[mesh.faces]:
                if triangle[:, 1].max() < band_low or triangle[:, 1].min() > band_high:
                    continue
                clipped = _clip_height(triangle, band_low, True)
                if len(clipped):
                    clipped = _clip_height(clipped, band_high, False)
                if len(clipped):
                    polygons.append(clipped[:, [0, 2]])
        for polygon in polygons:
            ids = candidates(polygon, cell_radius)
            occupied[ids] |= _contains(centers[ids], polygon, cell_radius)
    base = (supported.all(axis=1) & ~occupied).reshape(depth, width)
    clearance = distance_transform_edt(np.pad(base, 1))[1:-1, 1:-1] * CELL - CELL / 2
    free = base & (clearance >= request.clearance_m)
    components, _ = label(free)
    free_ids = np.flatnonzero(free)
    if not len(free_ids):
        raise AdapterError("No floor space has enough clearance between the modeled obstacles.")

    def endpoint_candidates(point, endpoint):
        if endpoint.point is not None:
            x, z = np.floor((point[[0, 2]] - origin) / CELL).astype(int)
            if not (0 <= x < width and 0 <= z < depth and free[z, x]):
                raise AdapterError(
                    "A selected point is outside the floor or too close to an obstacle."
                )
            return [(int(z * width + x), 0.0)]
        distances = np.linalg.norm(centers[free_ids] - point[[0, 2]], axis=1)
        # Doorway destinations mean the reachable approach, never a route through its panel.
        result = [(int(i), float(d)) for i, d in zip(free_ids, distances) if d <= 0.9]
        if not result:
            raise AdapterError("No clear floor approach was found within 0.9 m of that doorway.")
        return sorted(result, key=lambda item: item[1])

    starts = endpoint_candidates(start_point, request.start)
    ends = endpoint_candidates(end_point, request.end)
    end_by_component = {}
    for i, d in ends:
        end_by_component.setdefault(int(components.flat[i]), (i, d))
    pairs = [
        (
            d + end_by_component[int(components.flat[i])][1],
            i,
            end_by_component[int(components.flat[i])][0],
        )
        for i, d in starts
        if int(components.flat[i]) in end_by_component
    ]
    if not pairs:
        raise AdapterError(
            "No path connects these points on the modeled floor. Walls or gaps block it."
        )
    _, start_id, end_id = min(pairs)
    node_ids = {int(i): f"cell:{i}" for i in free_ids}
    nodes = [
        GraphNode(
            id=node_ids[int(i)],
            floor=1,
            position=(float(centers[i, 0]), float(elevation + 0.05), float(centers[i, 1])),
            kind="room",
            explored=False,
            clearance_m=float(clearance.flat[i]),
        )
        for i in free_ids
    ]
    edges = []
    for i in free_ids:
        z, x = divmod(int(i), width)
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
            nx, nz = x + dx, z + dz
            if not (0 <= nx < width and 0 <= nz < depth and free[nz, nx]):
                continue
            if dx and dz and not (free[z, nx] and free[nz, x]):
                continue
            edges.append(
                GraphEdge(
                    source=node_ids[int(i)],
                    target=node_ids[int(nz * width + nx)],
                    kind="walk",
                    length_m=CELL * (2**0.5 if dx and dz else 1),
                )
            )
    graph = BuildingGraph(
        id=scan_id,
        name="Rendered scene",
        cell_size=CELL,
        grid_origin=tuple(origin),
        floors=[1],
        nodes=nodes,
        edges=edges,
        hazards=[],
        rooms=[],
        entries=[],
        exits=[],
        default_start=node_ids[start_id],
        targets=[
            Target(
                id="destination",
                label=end_label,
                kind="room",
                node_id=node_ids[end_id],
                floor=1,
                position=(
                    float(centers[end_id, 0]),
                    float(elevation + 0.05),
                    float(centers[end_id, 1]),
                ),
                observed=False,
            )
        ],
    )
    result = plan(
        graph,
        Mission(mode="shortest", objectives=[Objective(kind="reach_target", ref="destination")]),
        smooth=False,
    )
    index = graph.index()
    # Keep the collision-checked grid edges. Generic planner smoothing is not used for
    # scene geometry because a smoothed shortcut can clip a wall corner.
    polyline = [index[node_id].position for node_id in result.legs[0].nodes]
    reduced = []
    for point in polyline:
        if len(reduced) >= 2:
            a = np.asarray(reduced[-1]) - reduced[-2]
            b = np.asarray(point) - reduced[-1]
            if np.linalg.norm(np.cross(a, b)) < 1e-8 and a @ b > 0:
                reduced.pop()
        reduced.append(point)
    warnings = [
        "Estimated path through the rendered model; "
        "missing geometry and real-world access are unverified."
    ]
    if request.start.object_id or request.end.object_id:
        warnings.append(
            "Doorway markers show a reachable approach, not a confirmed exit or an open door."
        )
    return dict(
        polyline=reduced,
        distance_m=round(sum(dist(a, b) for a, b in zip(polyline, polyline[1:])), 2),
        start=dict(point=polyline[0], label=start_label, object_id=request.start.object_id),
        end=dict(point=polyline[-1], label=end_label, object_id=request.end.object_id),
        estimated=True,
        warnings=warnings,
        clearance_m=request.clearance_m,
        cell_size=CELL,
    )
