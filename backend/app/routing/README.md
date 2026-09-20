# Mission routing

A* pathfinding for a team moving through a building we have only partly seen, plus the
agent that turns a spoken instruction into something the planner can execute.

**Nothing in this package knows how the building was reconstructed.** It is not wired to
any endpoint yet. To use it, write an adapter that turns the reconstruction's output into a
`BuildingGraph`; everything below then works unchanged.

```
reconstruction output  ──[ your adapter ]──▶  BuildingGraph
                                                   │
        instruction ──▶ MissionParser ──▶ Mission ─┤
                                                   ▼
                                            plan() ──▶ Route
                                                       (legs, polylines, risk, warnings)
```

## The two ideas worth keeping

**The agent reads intent; A\* picks the path.** `ClaudeMissionAgent` only ever produces a
`Mission` — ordered objectives, a mode, constraints. Every id it returns is checked against
the graph before the planner runs, so a hallucinated room or a person who was never detected
fails loudly instead of routing somewhere plausible and wrong. Routes stay reproducible and
testable. With no API key, `RuleBasedMissionParser` handles the same phrasings and needs no
network, which is what the tests use.

**Three states, not two.** A cell the cameras saw as solid is impassable; one they saw as
clear is cheap; one nobody ever saw is passable but expensive. Because a wall facing
observed space *is* observed, a route can only slip into unmapped space through a gap the
team actually looked through. Routes that do carry a warning and a metre count rather than a
promise, and `avoid_unmapped` refuses them outright. This is the whole reason the planner is
honest about a partial map, so an adapter should preserve it.

## What an adapter has to fill in

| Field | Meaning | If you have nothing for it |
|---|---|---|
| `nodes[].position` | Node centre, metres, Y up | required |
| `nodes[].floor` | Integer storey | use `1` everywhere |
| `nodes[].explored` | `False` = never observed | `True` everywhere disables unmapped costing |
| `nodes[].kind` | `corridor`/`room`/`doorway`/`stair`/`entry`/`exit`/`frontier`/`void` | `room` is a safe default |
| `nodes[].door_state` | `open`/`closed`/`locked`/`blocked`/`unknown` | `None` means freely passable |
| `nodes[].clearance_m` | Distance to nearest obstruction | `1.5` disables the tight-squeeze penalty |
| `edges[]` | Both directions. `length_m` is the true distance | required |
| `edges[].kind` | `walk`/`door`/`stair`. Stair edges are the only way between floors | `walk` |
| `hazards[]` | Zones with `radius_m` and `severity` 0–1 | empty; **shortest and safest then return the same route** |
| `targets[]` | What a mission can name, each pointing at a `node_id` | empty; only `reach_floor`/`exit_building` will resolve |
| `rooms[]` | Named rooms for `reach_room` | empty |
| `exits` / `default_start` | Node ids | `exit_building` and start resolution need these |

`grid_size`/`grid_origin` and the `f{floor}:{x},{z}` id convention are only used by route
smoothing, which string-pulls the grid staircase into a walkable line. If your nodes are not
on a grid, ids can be anything — smoothing will simply keep every node.

### Sketch: adapting a mesh or object scene

The video-reconstruction `Scene` gives objects with `position`, `size`, `rotation`,
`structural` and `entrance`. A workable adapter:

1. Take the scene's XZ extent and lay a grid over it, say 0.4–0.5 m per cell.
2. Rasterise each object's footprint at walking height. Mark those cells **occupied**.
3. Mark cells the camera path passed near, or within the reconstructed hull, as
   **explored**; leave the rest **unknown** so the warnings stay meaningful.
4. Link 8-connected neighbours, refusing to cut a blocked corner.
5. `entrance: true` objects become `exit` nodes; detected people become `targets`.
6. Operator annotations become `hazards` — without them, safest and shortest agree.

## Modes

`shortest` ≈ distance only. `safest` weights hazard exposure 5×, unmapped space 3×, and
stairs. `balanced` sits between. Every cost term is non-negative and added on top of the
edge's true length, so straight-line distance stays an admissible heuristic and A\* returns a
genuine optimum for the chosen cost model. `tests/test_pathfinder.py` checks this against a
brute-force Dijkstra on 32 random graphs.

## Not included

- The endpoint. Wire `plan()` up behind a route once an adapter exists.
- `ClaudeMissionAgent` has only been tested against a fake client, never the live API.
  `anthropic` is an optional import, so nothing breaks without it.
