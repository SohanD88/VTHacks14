"""Turning "get to floor 2, find person 3, then get out" into an executable mission.

The division of labour matters: the model reads intent, the planner finds the path. The
model's output is validated against real graph ids before it reaches the planner, so an
invented room or a person who was never detected produces a clear error instead of a
confident route to nowhere. With no API key configured the rule-based parser handles the
same phrasings, which is also what the tests run against.
"""

import json
import logging
import re
from typing import Protocol

from app.routing.graph import BuildingGraph
from app.routing.mission import Mission, MissionError, Objective, PlanningMode
from app.routing.planner import Route, RouteComparison

logger = logging.getLogger("spatial.agent")

MAX_TOOL_ITERATIONS = 3
SUBMIT_MISSION = {
    "name": "submit_mission",
    "description": (
        "Record the mission the operator described, using only ids that exist in the "
        "building brief. Objectives are listed in the order they must be completed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "objectives": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["reach_target", "reach_floor", "reach_room", "exit_building"],
                        },
                        "ref": {
                            "type": "string",
                            "description": (
                                "Target id for reach_target (e.g. 'person-3'), room id for "
                                "reach_room. Omit for reach_floor and exit_building."
                            ),
                        },
                        "floor": {"type": "integer", "description": "Required for reach_floor."},
                        "label": {
                            "type": "string",
                            "description": "Short human phrasing, e.g. 'reach Person 3'.",
                        },
                    },
                    "required": ["kind"],
                },
            },
            "mode": {
                "type": "string",
                "enum": ["shortest", "safest", "balanced"],
                "description": (
                    "shortest when speed is stressed, safest when risk or casualties are "
                    "stressed, balanced otherwise."
                ),
            },
            "ordered": {
                "type": "boolean",
                "description": "False only if the operator says the order does not matter.",
            },
            "avoid": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hazard ids or target ids the team must stay clear of.",
            },
            "avoid_unmapped": {
                "type": "boolean",
                "description": "True only if the operator insists on staying in mapped space.",
            },
            "allow_locked_doors": {
                "type": "boolean",
                "description": "True if forcing or breaching a locked door is acceptable.",
            },
            "notes": {
                "type": "string",
                "description": "Anything relevant the operator said that no other field covers.",
            },
        },
        "required": ["objectives", "mode"],
    },
}


class MissionParser(Protocol):
    def parse(self, instruction: str, graph: BuildingGraph) -> Mission: ...

    def narrate(
        self,
        mission: Mission,
        route: Route,
        graph: BuildingGraph,
        comparison: list[RouteComparison],
    ) -> str: ...


def describe_graph(graph: BuildingGraph) -> str:
    """A compact brief of everything the model is allowed to refer to."""
    lines = [f"BUILDING: {graph.name} (id {graph.id}), floors {graph.floors}."]
    lines.append("\nTARGETS (use these exact ids for reach_target):")
    for target in sorted(graph.targets, key=lambda t: (t.floor, t.id)):
        seen = "detected" if target.observed else "NOT detected — position is inferred only"
        confidence = f", confidence {target.confidence:.2f}" if target.confidence else ""
        lines.append(f"  {target.id} — {target.label}, floor {target.floor}, {seen}{confidence}")
    lines.append("\nROOMS (use these exact ids for reach_room):")
    for room in sorted(graph.rooms, key=lambda r: (r.floor, r.id)):
        lines.append(
            f"  {room.id} — {room.name}, floor {room.floor}, "
            f"{room.coverage_percent:.0f}% of its area mapped"
        )
    lines.append("\nHAZARDS (use these exact ids in `avoid`):")
    for hazard in graph.hazards:
        if hazard.kind == "obstacle":
            continue
        lines.append(f"  {hazard.id} — {hazard.label} (floor {hazard.floor}, {hazard.kind})")
    lines.append(f"\nEXITS: {len(graph.exits)} mapped. Use kind 'exit_building' to leave.")
    return "\n".join(lines)


SYSTEM_PROMPT = """You convert a field operator's spoken instruction into a structured \
mission for a route planner that works on a partially mapped building.

Rules:
- Call submit_mission exactly once. Never describe a route yourself; you do not choose the \
path, the planner does.
- Use only ids that appear in the building brief. If the operator names something that is \
not in the brief, do not invent an id — call submit_mission with the objectives you can \
resolve and explain the gap in `notes`.
- Objectives go in the order the operator implied. Leaving the building is always last.
- Pick `mode` from how the operator talks: urgency and speed mean shortest, casualties, \
risk, smoke, or structural damage mean safest, otherwise balanced."""

NARRATION_PROMPT = """You brief a field team on a route a planner has already computed.

Write 2-4 short sentences in plain, calm, operational language. Say which way the route \
goes and why, then the single most important risk. If part of the route crosses unmapped \
space, say so explicitly — the team must know the difference between geometry that was \
observed and geometry that was assumed. Never invent detail that is not in the data, and \
never contradict the numbers. No bullet points, no headings."""


class RuleBasedMissionParser:
    """Deterministic fallback. Handles the phrasings the demo uses, with no API key."""

    FLOOR = re.compile(r"(?:floor|level|storey|story)\s*#?\s*(\d+)|(\d+)(?:st|nd|rd|th)\s+floor")
    PERSON = re.compile(r"(?:person|casualty|victim|survivor|target)\s*#?-?\s*(\d+)")
    ROOM = re.compile(r"room\s*#?-?\s*([nsNS]\s?\d)")
    STAIR = re.compile(r"stair(?:well)?\s*([abAB])\b")
    EXIT = re.compile(
        r"\b(exit|leave|egress|evacuate|extract|exfil|withdraw|rtb|outside"
        r"|(?:get|head|back|pull|make our way|move) out|out of (?:there|the building))\b"
    )
    SAFE = re.compile(r"\b(safe|safest|careful|cautious|avoid|low[- ]risk|minimi[sz]e risk)\b")
    FAST = re.compile(r"\b(fast|fastest|short|shortest|quick|quickest|direct|speed|urgent)\b")

    def parse(self, instruction: str, graph: BuildingGraph) -> Mission:
        text = instruction.lower()
        targets = {target.id for target in graph.targets}
        rooms = {room.id for room in graph.rooms}
        found: list[tuple[int, Objective]] = []

        for match in self.FLOOR.finditer(text):
            floor = int(match.group(1) or match.group(2))
            if floor in graph.floors:
                found.append(
                    (
                        match.start(),
                        Objective(kind="reach_floor", floor=floor, label=f"reach floor {floor}"),
                    )
                )
        for match in self.PERSON.finditer(text):
            ref = f"person-{int(match.group(1))}"
            if ref in targets:
                found.append(
                    (
                        match.start(),
                        Objective(
                            kind="reach_target", ref=ref, label=f"reach {ref.replace('-', ' ')}"
                        ),
                    )
                )
        for match in self.ROOM.finditer(text):
            ref = f"room-{match.group(1).replace(' ', '').lower()}"
            for floor in graph.floors:
                if f"f{floor}-{ref}" in rooms:
                    found.append(
                        (
                            match.start(),
                            Objective(
                                kind="reach_room", ref=f"f{floor}-{ref}", label=f"reach {ref}"
                            ),
                        )
                    )
                    break
        for match in self.STAIR.finditer(text):
            ref = f"stair-{match.group(1).lower()}"
            if any(target.id.endswith(ref) for target in graph.targets):
                node = next(t.id for t in graph.targets if t.id.endswith(ref))
                found.append(
                    (match.start(), Objective(kind="reach_target", ref=node, label=f"reach {ref}"))
                )
        exit_match = self.EXIT.search(text)
        if exit_match:
            found.append(
                (
                    max(exit_match.start(), 10**6),
                    Objective(kind="exit_building", label="exit the building"),
                )
            )

        found.sort(key=lambda item: item[0])
        objectives, seen = [], set()
        for _, objective in found:
            key = (objective.kind, objective.ref, objective.floor)
            if key not in seen:
                seen.add(key)
                objectives.append(objective)
        if not objectives:
            raise MissionError(
                "Could not find an objective in that instruction.",
                suggestions=[
                    "get to floor 2, reach person 3, then leave the building",
                    "safest route to person 1 and back out",
                ],
            )

        mode: PlanningMode = "balanced"
        if self.SAFE.search(text):
            mode = "safest"
        elif self.FAST.search(text):
            mode = "shortest"
        return Mission(
            instruction=instruction[:600],
            objectives=objectives,
            mode=mode,
            avoid_unmapped=bool(
                re.search(
                    r"mapped (?:space|areas?) only|stay (?:in|on) mapped|avoid unmapped", text
                )
            ),  # noqa: E501
            allow_locked_doors=bool(re.search(r"breach|force (?:the )?door|locked", text)),
        )

    def narrate(
        self,
        mission: Mission,
        route: Route,
        graph: BuildingGraph,
        comparison: list[RouteComparison],
    ) -> str:
        floors = ", ".join(f"F{floor}" for floor in route.floors_visited)
        pace = (
            f"{route.total_duration_s:.0f} s"
            if route.total_duration_s < 120
            else f"{route.total_duration_s / 60:.0f} min"
        )
        parts = [
            f"{route.total_distance_m:.0f} m over {floors}, about {pace} at a walking pace, "
            f"{route.stair_transitions} stair transition(s)."
        ]
        if route.unexplored_m > 0.5:
            parts.append(
                f"{route.unexplored_m:.0f} m of it crosses space no camera has seen, so that "
                "stretch is assumed rather than observed."
            )
        if route.warnings:
            parts.append(f"Main risk: {route.warnings[0]}.")
        # Quote the alternative that actually differs, not just the next mode in the list.
        alternative = max(
            (c for c in comparison if c.mode != route.mode),
            key=lambda c: abs(c.risk_score - route.risk_score),
            default=None,
        )
        if alternative and abs(alternative.distance_m - route.total_distance_m) > 1:
            parts.append(
                f"For comparison, the {alternative.mode} route is "
                f"{alternative.distance_m:.0f} m at risk {alternative.risk_score:.2f} "
                f"against this one's {route.risk_score:.2f}."
            )
        return " ".join(parts)


class ClaudeMissionAgent:
    """Claude reads the instruction; the planner still decides the path.

    Falls back to the rule-based parser whenever the API is unreachable, so a demo never
    dies on a network blip.
    """

    def __init__(self, api_key: str, model: str = "claude-opus-5"):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.fallback = RuleBasedMissionParser()

    def parse(self, instruction: str, graph: BuildingGraph) -> Mission:
        brief = describe_graph(graph)
        messages = [
            {
                "role": "user",
                "content": f"{brief}\n\nOPERATOR INSTRUCTION:\n{instruction}",
            }
        ]
        problem: str | None = None
        for attempt in range(MAX_TOOL_ITERATIONS):
            if problem:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That mission was rejected: {problem}\n"
                            "Call submit_mission again using only ids from the brief above."
                        ),
                    }
                )
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    tools=[SUBMIT_MISSION],
                    tool_choice={"type": "tool", "name": "submit_mission"},
                    output_config={"effort": "low"},
                    messages=messages,
                )
            except self._anthropic.APIError as error:
                logger.warning("Mission agent unavailable (%s); using rule-based parser", error)
                return self.fallback.parse(instruction, graph)

            block = next((b for b in response.content if b.type == "tool_use"), None)
            if block is None:
                problem = "no submit_mission call was made"
                continue
            try:
                return _validate(dict(block.input), instruction, graph)
            except MissionError as error:
                problem = error.message
                messages.append({"role": "assistant", "content": response.content})
                logger.info("Mission rejected on attempt %d: %s", attempt + 1, problem)
        raise MissionError(
            f"Could not turn that instruction into a mission: {problem}",
            suggestions=[target.id for target in graph.targets[:6]],
        )

    def narrate(
        self,
        mission: Mission,
        route: Route,
        graph: BuildingGraph,
        comparison: list[RouteComparison],
    ) -> str:
        facts = {
            "mission": mission.summary(),
            "mode": route.mode,
            "distance_m": route.total_distance_m,
            "duration_min": round(route.total_duration_s / 60, 1),
            "floors": route.floors_visited,
            "stair_transitions": route.stair_transitions,
            "risk_score": route.risk_score,
            "unmapped_m": route.unexplored_m,
            "unmapped_percent": route.unexplored_percent,
            "warnings": route.warnings,
            "legs": [
                {
                    "objective": leg.objective.describe(),
                    "distance_m": leg.distance_m,
                    "floors": leg.floors,
                    "unmapped_m": leg.unexplored_m,
                }
                for leg in route.legs
            ],
            "alternatives": [c.model_dump() for c in comparison],
        }
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                system=NARRATION_PROMPT,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": json.dumps(facts, indent=2)}],
            )
        except self._anthropic.APIError as error:
            logger.warning("Narration unavailable (%s); using template brief", error)
            return self.fallback.narrate(mission, route, graph, comparison)
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return text or self.fallback.narrate(mission, route, graph, comparison)


def _validate(payload: dict, instruction: str, graph: BuildingGraph) -> Mission:
    """Everything the model produced has to correspond to something real."""
    targets = {target.id for target in graph.targets}
    rooms = {room.id for room in graph.rooms}
    hazards = {hazard.id for hazard in graph.hazards}

    raw = payload.get("objectives") or []
    if not isinstance(raw, list) or not raw:
        raise MissionError("no objectives were provided")
    objectives = []
    for item in raw:
        if not isinstance(item, dict):
            raise MissionError("an objective was not an object")
        kind = item.get("kind")
        ref, floor = item.get("ref"), item.get("floor")
        if kind == "reach_target" and ref not in targets:
            raise MissionError(
                f"'{ref}' is not a target in this capture (known: {', '.join(sorted(targets))})"
            )
        if kind == "reach_room" and ref not in rooms:
            raise MissionError(f"'{ref}' is not a mapped room in this capture")
        if kind == "reach_floor" and floor not in graph.floors:
            raise MissionError(f"floor {floor} is not part of this capture")
        objectives.append(
            Objective(
                kind=kind,
                ref=ref if kind in ("reach_target", "reach_room") else None,
                floor=floor if kind == "reach_floor" else None,
                label=str(item.get("label") or "")[:80],
            )
        )

    avoid = [
        ref
        for ref in payload.get("avoid") or []
        if ref in hazards or ref in targets or ref in ("danger", "caution", "obstacle")
    ]
    return Mission(
        instruction=instruction[:600],
        objectives=objectives,
        mode=payload.get("mode") if payload.get("mode") in WEIGHT_MODES else "balanced",
        ordered=bool(payload.get("ordered", True)),
        avoid=avoid,
        avoid_unmapped=bool(payload.get("avoid_unmapped", False)),
        allow_locked_doors=bool(payload.get("allow_locked_doors", False)),
        notes=str(payload.get("notes"))[:400] if payload.get("notes") else None,
    )


WEIGHT_MODES = ("shortest", "safest", "balanced")


def build_parser(api_key: str | None, model: str) -> MissionParser:
    if not api_key:
        logger.info("No Anthropic API key configured; missions parsed by rule")
        return RuleBasedMissionParser()
    return ClaudeMissionAgent(api_key=api_key, model=model)
