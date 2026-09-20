"""Multi-leg A* over the observed walkable graph.

The language model never picks a path. It produces a `Mission`; this module turns that into
a `Route` the same way every time, which is what makes the result testable and worth
trusting. Every cost term is non-negative and added on top of the edge's true length, so
straight-line distance stays an admissible heuristic and A* returns a genuine optimum for
the chosen cost model.
"""

import heapq
import math
from dataclasses import dataclass
from itertools import permutations

from pydantic import BaseModel, Field

from app.routing.graph import BuildingGraph, GraphEdge, GraphNode
from app.routing.mission import Mission, Objective, PlanningMode
from app.schemas import Vector3

WALK_SPEED = 1.25  # m/s on mapped flat ground
STAIR_SPEED = 0.5
UNMAPPED_SPEED = 0.7  # you move carefully through space nobody has seen
# Metres-equivalent cost of forcing a locked door. Only reachable when the mission allows
# it at all; the value is what breaching costs in time, not a number chosen to forbid it.
LOCKED_DOOR_COST = 12.0


@dataclass(frozen=True)
class Weights:
    hazard: float
    unknown: float
    door: float
    stair: float
    clearance: float


WEIGHTS: dict[PlanningMode, Weights] = {
    "shortest": Weights(hazard=0.15, unknown=0.25, door=0.3, stair=0.4, clearance=0.0),
    "balanced": Weights(hazard=1.4, unknown=1.1, door=1.0, stair=1.0, clearance=0.2),
    "safest": Weights(hazard=5.0, unknown=3.2, door=1.6, stair=2.0, clearance=0.6),
}
DOOR_PENALTY = {"open": 0.0, None: 0.0, "closed": 1.2, "unknown": 2.5, "blocked": 8.0}


class NoRouteError(Exception):
    """No path exists under the mission's constraints. `reason` says what got in the way."""

    def __init__(self, objective: str, reason: str):
        super().__init__(f"{objective}: {reason}")
        self.objective = objective
        self.reason = reason


class RouteLeg(BaseModel):
    index: int
    objective: Objective
    from_node: str
    to_node: str
    nodes: list[str]
    polyline: list[Vector3]
    distance_m: float
    duration_s: float
    risk: float = Field(ge=0)
    unexplored_m: float
    floors: list[int]
    warnings: list[str] = Field(default_factory=list)


class Route(BaseModel):
    mode: PlanningMode
    start_node: str
    legs: list[RouteLeg]
    total_distance_m: float
    total_duration_s: float
    risk_score: float = Field(ge=0)
    peak_risk: float = Field(ge=0)
    unexplored_m: float
    unexplored_percent: float
    floors_visited: list[int]
    stair_transitions: int
    warnings: list[str] = Field(default_factory=list)


class RouteComparison(BaseModel):
    mode: PlanningMode
    distance_m: float
    duration_s: float
    risk_score: float
    unexplored_m: float


class _Costs:
    """Per-mode edge costing, with the hazard field baked down to one number per node."""

    def __init__(self, graph: BuildingGraph, mission: Mission):
        self.graph = graph
        self.mission = mission
        self.weights = WEIGHTS[mission.mode]
        self.nodes = graph.index()
        self.adjacency = graph.adjacency()
        self.risk = self._risk_field()
        self.blocked = self._blocked()

    def _risk_field(self) -> dict[str, float]:
        field: dict[str, float] = {}
        by_floor: dict[int, list] = {}
        for hazard in self.graph.hazards:
            by_floor.setdefault(hazard.floor, []).append(hazard)
        for node in self.graph.nodes:
            total = 0.0
            for hazard in by_floor.get(node.floor, ()):
                dx = node.position[0] - hazard.position[0]
                dz = node.position[2] - hazard.position[2]
                distance = math.hypot(dx, dz)
                if distance < hazard.radius_m:
                    total += hazard.severity * (1 - distance / hazard.radius_m)
            field[node.id] = min(total, 3.0)
        return field

    def _blocked(self) -> set[str]:
        """Hard exclusions: what the mission said to avoid, plus unmapped space on request."""
        blocked: set[str] = set()
        if self.mission.avoid_unmapped:
            blocked.update(node.id for node in self.graph.nodes if not node.explored)
        if not self.mission.avoid:
            return blocked
        wanted = set(self.mission.avoid)
        zones = [h for h in self.graph.hazards if h.id in wanted or h.label in wanted]
        zones += [
            h for h in self.graph.hazards if any(ref in h.id or ref in h.kind for ref in wanted)
        ]
        spots = [(t.floor, t.position) for t in self.graph.targets if t.id in wanted]
        for node in self.graph.nodes:
            for hazard in zones:
                if (
                    node.floor == hazard.floor
                    and math.hypot(
                        node.position[0] - hazard.position[0], node.position[2] - hazard.position[2]
                    )
                    < hazard.radius_m
                ):
                    blocked.add(node.id)
            for floor, position in spots:
                if (
                    node.floor == floor
                    and math.hypot(node.position[0] - position[0], node.position[2] - position[2])
                    < 1.5
                ):
                    blocked.add(node.id)
        return blocked

    def door_cost(self, state: str | None) -> float | None:
        if state in ("locked", "blocked") and state == "locked":
            return LOCKED_DOOR_COST if self.mission.allow_locked_doors else None
        return DOOR_PENALTY.get(state, 0.0) * self.weights.door

    def edge_cost(self, edge: GraphEdge) -> float | None:
        target = self.nodes[edge.target]
        if target.id in self.blocked:
            return None
        door = self.door_cost(target.door_state)
        if door is None:
            return None
        weights = self.weights
        cost = edge.length_m
        cost += edge.length_m * weights.hazard * self.risk[target.id]
        if not target.explored:
            cost += edge.length_m * weights.unknown
        if target.clearance_m < 1.0:
            cost += edge.length_m * weights.clearance * (1.0 - target.clearance_m)
        cost += door
        if edge.kind == "stair":
            cost += 3.0 * weights.stair
        return cost

    def duration(self, edge: GraphEdge) -> float:
        target = self.nodes[edge.target]
        if edge.kind == "stair":
            return edge.length_m / STAIR_SPEED
        return edge.length_m / (WALK_SPEED if target.explored else UNMAPPED_SPEED)


def _goal_nodes(graph: BuildingGraph, objective: Objective) -> tuple[set[str], str]:
    """Resolve an objective to the set of nodes that satisfy it, or explain why it cannot be."""
    if objective.kind == "reach_target":
        target = next((t for t in graph.targets if t.id == objective.ref), None)
        if target is None:
            known = ", ".join(sorted(t.id for t in graph.targets)[:8])
            return set(), f"no target called '{objective.ref}' in this capture (known: {known})"
        return {target.node_id}, ""
    if objective.kind == "reach_room":
        room = next(
            (
                r
                for r in graph.rooms
                if objective.ref in (r.id, r.name) or r.id.endswith(f"-{objective.ref}")
            ),
            None,
        )
        if room is None or room.node_id is None:
            return set(), f"no room called '{objective.ref}' has been mapped"
        return {room.node_id}, ""
    if objective.kind == "reach_floor":
        nodes = {n.id for n in graph.nodes if n.floor == objective.floor}
        if not nodes:
            return set(), f"floor {objective.floor} is not part of this capture"
        return nodes, ""
    exits = set(graph.exits)
    if not exits:
        return set(), "no exit has been mapped yet"
    return exits, ""


def _heuristic(costs: _Costs, goals: set[str], objective: Objective):
    """Straight-line to the nearest goal. Never over-estimates, so A* stays optimal."""
    nodes = costs.nodes
    if objective.kind == "reach_floor":
        elevation = next(
            (n.position[1] for n in costs.graph.nodes if n.floor == objective.floor), 0.0
        )
        return lambda node_id: abs(nodes[node_id].position[1] - elevation)
    points = [nodes[goal].position for goal in goals]
    if len(points) > 48:  # a wide goal set is cheaper to search as plain Dijkstra
        return lambda node_id: 0.0

    def estimate(node_id: str) -> float:
        position = nodes[node_id].position
        return min(math.dist(position, point) for point in points)

    return estimate


def _astar(costs: _Costs, start: str, goals: set[str], objective: Objective) -> list[str]:
    if start in goals:
        return [start]
    heuristic = _heuristic(costs, goals, objective)
    best: dict[str, float] = {start: 0.0}
    came: dict[str, str] = {}
    queue: list[tuple[float, float, str]] = [(heuristic(start), 0.0, start)]
    seen: set[str] = set()
    while queue:
        _, spent, node_id = heapq.heappop(queue)
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id in goals:
            path = [node_id]
            while path[-1] != start:
                path.append(came[path[-1]])
            return path[::-1]
        for edge in costs.adjacency[node_id]:
            step = costs.edge_cost(edge)
            if step is None:
                continue
            total = spent + step
            if total < best.get(edge.target, math.inf):
                best[edge.target] = total
                came[edge.target] = node_id
                heapq.heappush(queue, (total + heuristic(edge.target), total, edge.target))
    raise NoRouteError(objective.describe(), _explain(costs, start, goals))


def _explain(costs: _Costs, start: str, goals: set[str]) -> str:
    """Say what actually blocked the search, rather than just 'unreachable'."""
    reasons = []
    if costs.mission.avoid_unmapped:
        if any(not costs.nodes[goal].explored for goal in goals):
            return "the objective sits in unmapped space and the mission forbids entering it"
        reasons.append("unmapped space is excluded")
    goal_floors = {costs.nodes[goal].floor for goal in goals}
    start_floor = costs.nodes[start].floor
    if goal_floors and start_floor not in goal_floors:
        stairs = [e for e in costs.graph.edges if e.kind == "stair"]
        usable = [
            e
            for e in stairs
            if costs.door_cost(costs.nodes[e.target].door_state) is not None
            and e.target not in costs.blocked
            and e.source not in costs.blocked
        ]
        if not usable:
            return "no usable stairwell connects those floors in the mapped area"
        reachable = {costs.nodes[e.target].floor for e in usable} | {
            costs.nodes[e.source].floor for e in usable
        }
        if not (goal_floors & reachable):
            return (
                f"no mapped stairwell reaches floor {sorted(goal_floors)[0]}; "
                "the only link found stops lower down"
            )
    if costs.mission.avoid:
        reasons.append(f"the avoid list ({', '.join(costs.mission.avoid)}) seals the only way in")
    locked = {n.door_state for n in costs.nodes.values() if n.door_state in ("locked", "blocked")}
    if locked and not costs.mission.allow_locked_doors:
        reasons.append("every remaining approach goes through a locked door")
    return "; ".join(reasons) if reasons else "the mapped space around it is fully enclosed"


def _line_of_sight(costs: _Costs, a: GraphNode, b: GraphNode) -> bool:
    """True when the straight segment only crosses cells we are allowed to stand in."""
    if a.floor != b.floor:
        return False
    cell = costs.graph.cell_size
    ox, oz = costs.graph.grid_origin
    distance = math.dist((a.position[0], a.position[2]), (b.position[0], b.position[2]))
    for step in range(1, int(distance / (cell * 0.5)) + 1):
        ratio = step / (distance / (cell * 0.5))
        x = a.position[0] + (b.position[0] - a.position[0]) * ratio
        z = a.position[2] + (b.position[2] - a.position[2]) * ratio
        node_id = f"f{a.floor}:{int((x - ox) / cell)},{int((z - oz) / cell)}"
        node = costs.nodes.get(node_id)
        if node is None or node_id in costs.blocked:
            return False
        if costs.door_cost(node.door_state) is None:
            return False
    return True


def _smooth(costs: _Costs, path: list[str]) -> list[Vector3]:
    """String-pull the grid staircase into the line a person would actually walk."""
    if len(path) < 2:
        return [costs.nodes[node_id].position for node_id in path]
    points: list[Vector3] = [costs.nodes[path[0]].position]
    anchor = 0
    while anchor < len(path) - 1:
        furthest = anchor + 1
        for candidate in range(len(path) - 1, anchor, -1):
            if _line_of_sight(costs, costs.nodes[path[anchor]], costs.nodes[path[candidate]]):
                furthest = candidate
                break
        points.append(costs.nodes[path[furthest]].position)
        anchor = furthest
    return points


def _leg_stats(costs: _Costs, path: list[str]) -> dict:
    edges = {(e.source, e.target): e for e in costs.graph.edges}
    distance = duration = unexplored = weighted_risk = peak = 0.0
    stairs = 0
    used_doors: dict[str, str] = {}
    for source, target in zip(path, path[1:]):
        edge = edges.get((source, target))
        if edge is None:
            continue
        node = costs.nodes[target]
        distance += edge.length_m
        duration += costs.duration(edge)
        if not node.explored:
            unexplored += edge.length_m
        risk = costs.risk[target]
        weighted_risk += risk * edge.length_m
        peak = max(peak, risk)
        if edge.kind == "stair":
            stairs += 1
        if node.door_state in ("locked", "blocked", "closed", "unknown"):
            used_doors[node.id] = node.door_state
    return {
        "distance": distance,
        "duration": duration,
        "unexplored": unexplored,
        "risk": weighted_risk / distance if distance else 0.0,
        "peak": peak,
        "stairs": stairs,
        "doors": used_doors,
    }


def _warnings(costs: _Costs, path: list[str], stats: dict) -> list[str]:
    messages: list[str] = []
    if stats["unexplored"] > 0.75:
        messages.append(
            f"{stats['unexplored']:.0f} m of this leg crosses unmapped space — "
            "geometry beyond the frontier is assumed, not observed"
        )
    exposure: dict[str, float] = {}
    for node_id in path:
        node = costs.nodes[node_id]
        for hazard in costs.graph.hazards:
            if hazard.floor != node.floor or hazard.kind == "obstacle":
                continue
            distance = math.hypot(
                node.position[0] - hazard.position[0], node.position[2] - hazard.position[2]
            )
            if distance < hazard.radius_m:
                exposure[hazard.label] = min(exposure.get(hazard.label, 99.0), distance)
    for label, distance in sorted(exposure.items(), key=lambda item: item[1]):
        messages.append(f"passes within {distance:.1f} m of: {label}")
    for state in set(stats["doors"].values()):
        if state == "locked":
            messages.append("forces a door reported locked — breaching kit required")
        elif state == "blocked":
            messages.append("uses a door reported blocked")
        elif state == "unknown":
            messages.append("uses a door whose state was never confirmed")
    if stats["stairs"]:
        messages.append(f"{stats['stairs']} stair transition(s)")
    return messages


def _resolve(graph: BuildingGraph, mission: Mission) -> list[tuple[Objective, set[str]]]:
    resolved = []
    for objective in mission.objectives:
        goals, problem = _goal_nodes(graph, objective)
        if not goals:
            raise NoRouteError(objective.describe(), problem)
        resolved.append((objective, goals))
    return resolved


def plan(graph: BuildingGraph, mission: Mission) -> Route:
    costs = _Costs(graph, mission)
    start = mission.start_node or graph.default_start
    if start is None or start not in costs.nodes:
        raise NoRouteError("start", "the capture has no mapped entry point to start from")
    if start in costs.blocked:
        raise NoRouteError("start", "the start point falls inside an avoided zone")

    resolved = _resolve(graph, mission)
    if not mission.ordered and 1 < len(resolved) <= 6:
        resolved = _best_order(costs, start, resolved)

    legs: list[RouteLeg] = []
    cursor = start
    for index, (objective, goals) in enumerate(resolved, 1):
        path = _astar(costs, cursor, goals, objective)
        stats = _leg_stats(costs, path)
        legs.append(
            RouteLeg(
                index=index,
                objective=objective,
                from_node=cursor,
                to_node=path[-1],
                nodes=path,
                polyline=_smooth(costs, path),
                distance_m=round(stats["distance"], 1),
                duration_s=round(stats["duration"], 1),
                risk=round(stats["risk"], 3),
                unexplored_m=round(stats["unexplored"], 1),
                floors=sorted({costs.nodes[node_id].floor for node_id in path}),
                warnings=_warnings(costs, path, stats),
            )
        )
        cursor = path[-1]

    distance = sum(leg.distance_m for leg in legs)
    unexplored = sum(leg.unexplored_m for leg in legs)
    risk = sum(leg.risk * leg.distance_m for leg in legs) / distance if distance else 0.0
    warnings: list[str] = []
    for leg in legs:
        for message in leg.warnings:
            if message not in warnings:
                warnings.append(message)
    return Route(
        mode=mission.mode,
        start_node=start,
        legs=legs,
        total_distance_m=round(distance, 1),
        total_duration_s=round(sum(leg.duration_s for leg in legs), 1),
        risk_score=round(risk, 3),
        peak_risk=round(max((leg.risk for leg in legs), default=0.0), 3),
        unexplored_m=round(unexplored, 1),
        unexplored_percent=round(100 * unexplored / distance, 1) if distance else 0.0,
        floors_visited=sorted({floor for leg in legs for floor in leg.floors}),
        stair_transitions=sum(
            1
            for leg in legs
            for pair in zip(leg.nodes, leg.nodes[1:])
            if costs.nodes[pair[0]].floor != costs.nodes[pair[1]].floor
        ),
        warnings=warnings,
    )


def _best_order(
    costs: _Costs, start: str, resolved: list[tuple[Objective, set[str]]]
) -> list[tuple[Objective, set[str]]]:
    """Brute-force the visiting order. Capped at 6 objectives, so 720 orderings at worst."""
    exits = [item for item in resolved if item[0].kind == "exit_building"]
    middle = [item for item in resolved if item[0].kind != "exit_building"]
    best, best_cost = None, math.inf
    for order in permutations(middle):
        cursor, total = start, 0.0
        try:
            for objective, goals in order:
                path = _astar(costs, cursor, goals, objective)
                total += _leg_stats(costs, path)["distance"]
                cursor = path[-1]
        except NoRouteError:
            continue
        if total < best_cost:
            best, best_cost = list(order), total
    if best is None:
        return resolved
    return best + exits  # leaving the building is always the last thing you do


def compare(graph: BuildingGraph, mission: Mission) -> list[RouteComparison]:
    """The same objectives under each mode, so an operator can see what safety costs."""
    results = []
    for mode in ("shortest", "balanced", "safest"):
        try:
            route = plan(graph, mission.model_copy(update={"mode": mode}))
        except NoRouteError:
            continue
        results.append(
            RouteComparison(
                mode=mode,
                distance_m=route.total_distance_m,
                duration_s=route.total_duration_s,
                risk_score=route.risk_score,
                unexplored_m=route.unexplored_m,
            )
        )
    return results
