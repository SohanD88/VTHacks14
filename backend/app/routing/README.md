# Mission routing

A* pathfinding for a team moving through a building we have only partly seen, plus the
agent that turns a spoken instruction into something the planner can execute.

The planner consumes a `BuildingGraph`. `scene_adapter.py` now builds one from the saved
rendered scene and `POST /api/scans/{scan_id}/routes` returns a point-to-point route.
The Sandbox's **Pathfinder** panel lets you choose floor points by clicking the model,
or choose doorway objects, then draws the estimated path and endpoint markers.

## Routes through a rendered scene

Send the current scan revision and two endpoints. Each endpoint contains exactly one
of `point` (world XYZ, Y up, estimated meters) or `object_id` (an existing doorway):

```json
{
  "revision": 0,
  "start": {"point": [0, 0, 0]},
  "end": {"object_id": "your-door-id"},
  "clearance_m": 0.2
}
```

The response contains `scan_id`, `revision`, `polyline`, `distance_m`, resolved `start`
and `end` points, `estimated: true`, and `warnings`. There is no extra model call or API
key for point-to-point routing. It uses the existing A* engine with collinear grid edges
combined for display; shortcuts across obstacle corners are not permitted.

The adapter applies the same XYZ transforms as the viewer, rasterizes horizontal floor
triangles at 15 cm resolution, blocks mesh surfaces at walking height, and keeps the
requested clearance (default 20 cm). Furniture uses conservative bounds. Hidden and
low-confidence geometry still blocks routes. Deleted objects are excluded. Doorway
destinations stop at a reachable approach within 90 cm; a label never punches a hole in
a wall, opens a closed panel, or establishes an exit. Missing floor geometry is blocked.

This is **estimated navigation through the model**, not observed free-space mapping.
It works with Blender renders that have no camera path, but cannot verify physical access
or hazards. Both endpoints must be on the same level. Stairs and cross-floor routing
require an explicit connection model. Grid size, mesh complexity, and computation are
bounded; unsupported scenes return a readable 422 error. Missing scans return 404;
unfinished scans and outdated revisions return 409. Edits clear the viewer's route and
the endpoint checks the scene revision again after planning to prevent stale results.

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

## Modes

`shortest` ≈ distance only. `safest` weights hazard exposure 5×, unmapped space 3×, and
stairs. `balanced` sits between. Every cost term is non-negative and added on top of the
edge's true length, so straight-line distance stays an admissible heuristic and A\* returns a
genuine optimum for the chosen cost model. `tests/test_pathfinder.py` checks this against a
brute-force Dijkstra on 32 random graphs.

## Not included

- Mission instructions, hazards, verified exits, and multi-floor connectivity are not
  exposed by the scene route endpoint; it accepts two points or doorway destinations.
- `ClaudeMissionAgent` has only been tested against a fake client, never the live API.
  `anthropic` is an optional import, so nothing breaks without it.
