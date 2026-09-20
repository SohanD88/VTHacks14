"""A* mission planning over a partially mapped building.

These tests build `BuildingGraph`s directly from small ASCII maps, so they exercise the
planner without depending on any particular reconstruction. When an adapter is written for
the video-reconstruction `Scene`, its own tests cover the translation; everything here
keeps holding.
"""

import heapq
import math
import random

import pytest

from app.routing.graph import BuildingGraph, GraphEdge, GraphNode, HazardZone, RoomRef, Target
from app.routing.mission import Mission, MissionError, Objective
from app.routing.mission_parser import RuleBasedMissionParser
from app.routing.planner import NoRouteError, _astar, _Costs, compare, plan

CELL = 0.5
# Uniform clearance keeps these fixtures focused on the term each test is about.
CLEARANCE = 1.5
STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

# ASCII legend. '#' is solid, '?' was never observed, everything else was.
KINDS = {".": "corridor", "?": "void", "S": "stair", "E": "exit", "N": "entry"}


def build(
    layouts: dict[int, list[str]],
    *,
    doors: dict[tuple[int, int, int], str] | None = None,
    hazards=(),
    targets=(),
    rooms=(),
    start: str | None = None,
) -> BuildingGraph:
    """Assemble a graph from one ASCII map per floor. `doors` keys are (floor, x, z)."""
    doors = doors or {}
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    passable: dict[int, set[tuple[int, int]]] = {}

    for floor, rows in layouts.items():
        elevation = (floor - 1) * 3.2
        open_cells = {
            (x, z) for z, row in enumerate(rows) for x, char in enumerate(row) if char != "#"
        }
        passable[floor] = open_cells
        for x, z in open_cells:
            char = rows[z][x]
            explored = char != "?"
            kind = KINDS.get(char, "room")
            state = doors.get((floor, x, z))
            if state:
                kind = "doorway"
            if kind == "void" and any(
                (x + dx, z + dz) in open_cells and rows[z + dz][x + dx] != "?"
                for dx, dz in STEPS[:4]
                if 0 <= z + dz < len(rows) and 0 <= x + dx < len(rows[0])
            ):
                kind = "frontier"
            node_id = f"f{floor}:{x},{z}"
            nodes[node_id] = GraphNode(
                id=node_id,
                floor=floor,
                position=((x + 0.5) * CELL, elevation + 0.9, (z + 0.5) * CELL),
                kind=kind,
                explored=explored,
                door_state=state,
                clearance_m=CLEARANCE,
            )
        for x, z in open_cells:
            for dx, dz in STEPS:
                if (x + dx, z + dz) not in open_cells:
                    continue
                if dx and dz and not ((x + dx, z) in open_cells and (x, z + dz) in open_cells):
                    continue  # never cut a blocked corner
                target = nodes[f"f{floor}:{x + dx},{z + dz}"]
                edges.append(
                    GraphEdge(
                        source=f"f{floor}:{x},{z}",
                        target=target.id,
                        kind="door" if target.kind == "doorway" else "walk",
                        length_m=round(CELL * (1.4142 if dx and dz else 1.0), 3),
                        door_state=target.door_state,
                    )
                )

    # Stair landings at the same cell on consecutive floors are the only way between them.
    landings: dict[tuple[int, int], list[int]] = {}
    for floor, rows in layouts.items():
        for z, row in enumerate(rows):
            for x, char in enumerate(row):
                if char == "S":
                    landings.setdefault((x, z), []).append(floor)
    for (x, z), floors in landings.items():
        for floor in sorted(floors):
            if floor + 1 in floors:
                lower, upper = f"f{floor}:{x},{z}", f"f{floor + 1}:{x},{z}"
                for source, goal in ((lower, upper), (upper, lower)):
                    edges.append(GraphEdge(source=source, target=goal, kind="stair", length_m=7.5))

    entries = [n.id for n in nodes.values() if n.kind == "entry"]
    exits = [n.id for n in nodes.values() if n.kind in ("exit", "entry")]
    return BuildingGraph(
        id="fixture",
        name="Fixture",
        cell_size=CELL,
        grid_origin=(0.0, 0.0),
        floors=sorted(layouts),
        nodes=list(nodes.values()),
        edges=edges,
        hazards=[
            HazardZone(
                id=hid,
                label=label,
                floor=floor,
                position=((x + 0.5) * CELL, (floor - 1) * 3.2 + 0.9, (z + 0.5) * CELL),
                radius_m=radius,
                severity=severity,
                kind="danger",
            )
            for hid, label, floor, x, z, radius, severity in hazards
        ],
        targets=[
            Target(
                id=tid,
                label=label,
                kind=kind,
                node_id=f"f{floor}:{x},{z}",
                floor=floor,
                position=nodes[f"f{floor}:{x},{z}"].position,
                observed=nodes[f"f{floor}:{x},{z}"].explored,
            )
            for tid, label, kind, floor, x, z in targets
        ],
        rooms=[
            RoomRef(
                id=rid, name=name, floor=floor, node_id=f"f{floor}:{x},{z}", coverage_percent=80.0
            )
            for rid, name, floor, x, z in rooms
        ],
        entries=entries,
        exits=exits,
        default_start=start or (entries[0] if entries else None),
    )


def mission(*objectives: Objective, **kwargs) -> Mission:
    return Mission(objectives=list(objectives), **kwargs)


# A loop with one hazardous side: the short way past the hazard, the long way around.
# The start sits clear of the hazard radius so both routes are judged on the detour alone.
HAZARD_MAP = [
    "###############",
    "#N............#",
    "#.###########.#",
    "#.###########.#",
    "#.###########.#",
    "#H###########.#",
    "#.###########.#",
    "#.###########.#",
    "#......T......#",
    "###############",
]
HAZARD_GRAPH = build(
    {1: HAZARD_MAP},
    hazards=[("haz-1", "Collapsed ceiling", 1, 1, 5, 1.9, 0.95)],
    targets=[("person-1", "Person 1", "person", 1, 7, 8)],
)
REACH_P1 = Objective(kind="reach_target", ref="person-1")


def test_shortest_takes_the_hazard_and_safest_goes_around():
    short = plan(HAZARD_GRAPH, mission(REACH_P1, mode="shortest"))
    safe = plan(HAZARD_GRAPH, mission(REACH_P1, mode="safest"))
    assert short.total_distance_m < safe.total_distance_m
    assert safe.risk_score < short.risk_score
    # The two routes must differ in shape, not merely in cost.
    assert short.legs[0].nodes != safe.legs[0].nodes
    assert any("Collapsed ceiling" in w for w in short.warnings)
    assert not any("Collapsed ceiling" in w for w in safe.warnings)


def test_compare_reports_every_mode_in_order():
    results = compare(HAZARD_GRAPH, mission(REACH_P1))
    assert [r.mode for r in results] == ["shortest", "balanced", "safest"]
    assert results[0].distance_m <= results[-1].distance_m


# A near exit behind a locked door, and a far one standing open. The team starts at x=4,
# on a plain cell: an entry cell would satisfy "exit the building" where it stood.
LOCKED_MAP = ["#" * 37, "#EL" + "." * 32 + "E#", "#" * 37]
LOCKED_GRAPH = build({1: LOCKED_MAP}, doors={(1, 2, 1): "locked"}, start="f1:4,1")
LEAVE = Objective(kind="exit_building")


def test_a_locked_door_is_refused_until_the_mission_allows_breaching():
    closed = plan(LOCKED_GRAPH, mission(LEAVE, mode="shortest"))
    forced = plan(LOCKED_GRAPH, mission(LEAVE, mode="shortest", allow_locked_doors=True))
    assert closed.legs[-1].to_node == "f1:35,1", "must walk to the far exit"
    assert forced.legs[-1].to_node == "f1:1,1", "breaching makes the near exit worth it"
    assert forced.total_distance_m < closed.total_distance_m
    assert any("locked" in w for w in forced.warnings)
    assert not any("locked" in w for w in closed.warnings)


# A target sitting past the frontier, in space nobody observed.
UNMAPPED_MAP = ["#" * 13, "#N...D???T??#", "#" * 13]
UNMAPPED_GRAPH = build(
    {1: UNMAPPED_MAP},
    doors={(1, 5, 1): "open"},
    targets=[("person-2", "Person 2", "person", 1, 9, 1)],
)
REACH_P2 = Objective(kind="reach_target", ref="person-2")


def test_unmapped_space_is_costed_warned_about_then_refused():
    route = plan(UNMAPPED_GRAPH, mission(REACH_P2))
    assert route.unexplored_m > 1
    assert route.unexplored_percent > 0
    assert any("unmapped" in w for w in route.warnings)
    with pytest.raises(NoRouteError) as raised:
        plan(UNMAPPED_GRAPH, mission(REACH_P2, avoid_unmapped=True))
    assert "unmapped" in raised.value.reason


def test_the_frontier_is_the_only_way_into_unmapped_space():
    index = UNMAPPED_GRAPH.index()
    crossings = [
        e for e in UNMAPPED_GRAPH.edges if index[e.source].explored and not index[e.target].explored
    ]
    assert crossings
    assert all(index[e.target].kind in ("frontier", "void", "doorway") for e in crossings)


# Two floors joined only at a stair landing.
TOWER = {
    1: ["#########", "#N..S...#", "#########"],
    2: ["#########", "#T..S...#", "#########"],
}
TOWER_GRAPH = build(
    TOWER,
    targets=[("person-3", "Person 3", "person", 2, 1, 1)],
    rooms=[("f2-room-a", "Room A", 2, 6, 1)],
)
REACH_F2 = Objective(kind="reach_floor", floor=2)
REACH_P3 = Objective(kind="reach_target", ref="person-3")


def test_floors_are_joined_only_by_stair_landings():
    stair_edges = [e for e in TOWER_GRAPH.edges if e.kind == "stair"]
    index = TOWER_GRAPH.index()
    assert stair_edges
    assert all(index[e.source].floor != index[e.target].floor for e in stair_edges)


def test_a_multi_leg_mission_runs_its_objectives_in_order():
    route = plan(TOWER_GRAPH, mission(REACH_F2, REACH_P3, LEAVE))
    assert [leg.objective.kind for leg in route.legs] == [
        "reach_floor",
        "reach_target",
        "exit_building",
    ]
    assert route.legs[0].from_node == route.start_node
    assert all(leg.from_node == route.legs[i - 1].to_node for i, leg in enumerate(route.legs) if i)
    assert 2 in route.legs[0].floors
    assert route.stair_transitions >= 2, "up, and back down to leave"
    assert route.total_distance_m == pytest.approx(
        sum(leg.distance_m for leg in route.legs), abs=0.2
    )


def test_an_unordered_mission_is_reordered_and_the_exit_stays_last():
    route = plan(TOWER_GRAPH, mission(LEAVE, REACH_P3, ordered=False))
    assert route.legs[-1].objective.kind == "exit_building"


def test_polylines_are_smoothed_but_still_start_and_end_on_the_route():
    route = plan(TOWER_GRAPH, mission(REACH_F2, REACH_P3, LEAVE))
    index = TOWER_GRAPH.index()
    for leg in route.legs:
        assert len(leg.polyline) >= 2
        assert len(leg.polyline) <= len(leg.nodes), "grid stair-stepping should collapse"
        assert leg.polyline[0] == index[leg.from_node].position
        assert leg.polyline[-1] == index[leg.to_node].position


def test_a_reachable_room_objective_resolves_by_id_or_name():
    for ref in ("f2-room-a", "Room A"):
        route = plan(TOWER_GRAPH, mission(Objective(kind="reach_room", ref=ref)))
        assert route.legs[-1].to_node == "f2:6,1"


@pytest.mark.parametrize(
    "objective, fragment",
    [
        (Objective(kind="reach_target", ref="person-99"), "person-99"),
        (Objective(kind="reach_floor", floor=9), "floor 9"),
        (Objective(kind="reach_room", ref="the-attic"), "the-attic"),
    ],
)
def test_objectives_that_do_not_exist_are_named_in_the_error(objective, fragment):
    with pytest.raises(NoRouteError) as raised:
        plan(TOWER_GRAPH, mission(objective))
    assert fragment in raised.value.reason


def test_a_sealed_objective_explains_what_blocked_it():
    sealed = build(
        {1: ["#####", "#N#T#", "#####"]}, targets=[("person-4", "P4", "person", 1, 3, 1)]
    )
    with pytest.raises(NoRouteError) as raised:
        plan(sealed, mission(Objective(kind="reach_target", ref="person-4")))
    assert raised.value.reason
    assert raised.value.objective


def test_planning_without_a_start_point_fails_clearly():
    orphan = build({1: ["###", "#.#", "###"]})
    with pytest.raises(NoRouteError) as raised:
        plan(orphan, mission(Objective(kind="reach_floor", floor=1)))
    assert "start" in raised.value.objective


# --- The mission agent's deterministic path, which needs no API key ----------------------


@pytest.fixture
def parser():
    return RuleBasedMissionParser()


@pytest.mark.parametrize(
    "instruction, kinds, mode",
    [
        (
            "get to floor 2, reach person 3, then leave the building",
            ["reach_floor", "reach_target", "exit_building"],
            "balanced",
        ),
        ("safest route to person 3 and back out", ["reach_target", "exit_building"], "safest"),
        ("fastest way to the 2nd floor", ["reach_floor"], "shortest"),
        ("find casualty 3 then evacuate", ["reach_target", "exit_building"], "balanced"),
    ],
)
def test_the_rule_based_parser_handles_operator_phrasings(parser, instruction, kinds, mode):
    parsed = parser.parse(instruction, TOWER_GRAPH)
    assert [o.kind for o in parsed.objectives] == kinds
    assert parsed.mode == mode


def test_the_parser_never_invents_a_person_who_was_not_detected(parser):
    parsed = parser.parse("reach person 9 then person 3", TOWER_GRAPH)
    assert [o.ref for o in parsed.objectives] == ["person-3"]


def test_the_parser_reads_constraints_and_refuses_nonsense(parser):
    assert parser.parse("reach person 3, mapped space only", TOWER_GRAPH).avoid_unmapped
    assert parser.parse("breach the door and exit", TOWER_GRAPH).allow_locked_doors
    with pytest.raises(MissionError) as raised:
        parser.parse("what is the weather like", TOWER_GRAPH)
    assert raised.value.suggestions


def test_a_parsed_instruction_plans_end_to_end(parser):
    parsed = parser.parse("get to floor 2, reach person 3, then leave", TOWER_GRAPH)
    route = plan(TOWER_GRAPH, parsed)
    assert len(route.legs) == 3
    brief = parser.narrate(parsed, route, TOWER_GRAPH, compare(TOWER_GRAPH, parsed))
    assert f"{route.total_distance_m:.0f} m" in brief


# --- Optimality --------------------------------------------------------------------------


def _dijkstra(costs: _Costs, start: str, goal: str) -> float:
    """Ground truth: no heuristic, so there is no way for one to be wrong."""
    best = {start: 0.0}
    queue = [(0.0, start)]
    seen: set[str] = set()
    while queue:
        spent, node = heapq.heappop(queue)
        if node in seen:
            continue
        seen.add(node)
        if node == goal:
            return spent
        for edge in costs.adjacency[node]:
            step = costs.edge_cost(edge)
            if step is None:
                continue
            if spent + step < best.get(edge.target, math.inf):
                best[edge.target] = spent + step
                heapq.heappush(queue, (spent + step, edge.target))
    return math.inf


def _random_graph(seed: int) -> BuildingGraph:
    rng = random.Random(seed)
    size = 7
    rows = [
        "".join("#" if rng.random() < 0.25 else rng.choice("...?") for _ in range(size))
        for _ in range(size)
    ]
    doors = {
        (1, x, z): rng.choice(["closed", "unknown"])
        for x in range(size)
        for z in range(size)
        if rows[z][x] != "#" and rng.random() < 0.12
    }
    hazards = [("h", "Rubble", 1, rng.randrange(size), rng.randrange(size), 1.5, 0.8)]
    return build({1: rows}, doors=doors, hazards=hazards)


@pytest.mark.parametrize("seed", range(16))
@pytest.mark.parametrize("mode", ["shortest", "safest"])
def test_astar_matches_dijkstra_so_the_heuristic_is_admissible(seed, mode):
    small = _random_graph(seed)
    ids = [node.id for node in small.nodes]
    if len(ids) < 2:
        pytest.skip("degenerate map")
    start, goal = ids[0], ids[-1]
    objective = Objective(kind="reach_target", ref=goal)
    costs = _Costs(small, mission(objective, mode=mode))
    optimal = _dijkstra(costs, start, goal)
    try:
        path = _astar(costs, start, {goal}, objective)
    except NoRouteError:
        assert optimal == math.inf
        return
    edges = {(e.source, e.target): e for e in small.edges}
    total = sum(costs.edge_cost(edges[(a, b)]) for a, b in zip(path, path[1:]))
    assert total == pytest.approx(optimal, rel=1e-9)
