"""The navigation contract between "what we mapped" and "where we can go".

A `BuildingGraph` is the only thing the planner sees. Nothing in this package knows how the
graph was produced, which is the point: an adapter turns whatever the reconstruction emits
into this shape, and the planner and the mission agent are unchanged either way. See
`README.md` in this package for what an adapter has to fill in.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Vector3

DoorState = Literal["open", "closed", "locked", "blocked", "unknown"]
NodeKind = Literal["corridor", "room", "doorway", "stair", "entry", "exit", "frontier", "void"]
EdgeKind = Literal["walk", "door", "stair"]
TargetKind = Literal["person", "room", "exit", "entry", "stair", "floor"]


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    floor: int
    position: Vector3
    kind: NodeKind
    explored: bool
    room_id: str | None = None
    door_state: DoorState | None = None
    clearance_m: float = 0.0  # distance to the nearest known obstruction


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    kind: EdgeKind
    length_m: float
    door_state: DoorState | None = None


class HazardZone(BaseModel):
    id: str
    label: str
    floor: int
    position: Vector3
    radius_m: float = Field(gt=0)
    severity: float = Field(ge=0, le=1)
    kind: str = "annotation"


class Target(BaseModel):
    """Something a mission can name. `node_id` is where the planner actually routes to."""

    id: str
    label: str
    kind: TargetKind
    node_id: str
    floor: int
    position: Vector3
    confidence: float | None = None
    observed: bool = True


class RoomRef(BaseModel):
    id: str
    name: str
    floor: int
    node_id: str | None
    coverage_percent: float


class BuildingGraph(BaseModel):
    id: str
    name: str
    cell_size: float
    grid_origin: tuple[float, float]  # world x, z of cell (0, 0); node ids are cell indices
    floors: list[int]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hazards: list[HazardZone]
    targets: list[Target]
    rooms: list[RoomRef]
    entries: list[str]
    exits: list[str]
    default_start: str | None = None

    def index(self) -> dict[str, GraphNode]:
        return {node.id: node for node in self.nodes}

    def adjacency(self) -> dict[str, list[GraphEdge]]:
        table: dict[str, list[GraphEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            table[edge.source].append(edge)
        return table


class BuildingSummary(BaseModel):
    """What `GET /api/buildings/{id}` returns. The full node list stays server-side."""

    id: str
    name: str
    cell_size: float
    floors: list[int]
    node_count: int
    edge_count: int
    explored_nodes: int
    hazards: list[HazardZone]
    targets: list[Target]
    rooms: list[RoomRef]
    entries: list[str]
    exits: list[str]
    default_start: str | None


def summarize(graph: BuildingGraph) -> BuildingSummary:
    return BuildingSummary(
        id=graph.id,
        name=graph.name,
        cell_size=graph.cell_size,
        floors=graph.floors,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        explored_nodes=sum(node.explored for node in graph.nodes),
        hazards=graph.hazards,
        targets=graph.targets,
        rooms=graph.rooms,
        entries=graph.entries,
        exits=graph.exits,
        default_start=graph.default_start,
    )
