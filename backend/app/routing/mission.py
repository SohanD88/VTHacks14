"""What the team is being asked to do, separate from how they get there.

A `Mission` is the only thing the language model is allowed to produce. Every field is
validated against real graph ids before the planner sees it, so a hallucinated room or a
person who was never detected fails loudly instead of quietly routing somewhere wrong.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PlanningMode = Literal["shortest", "safest", "balanced"]
ObjectiveKind = Literal["reach_target", "reach_floor", "reach_room", "exit_building"]


class Objective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ObjectiveKind
    ref: str | None = None  # target id for reach_target, room id for reach_room
    floor: int | None = None  # required for reach_floor
    label: str = ""

    def describe(self) -> str:
        if self.label:
            return self.label
        if self.kind == "reach_floor":
            return f"reach floor {self.floor}"
        if self.kind == "exit_building":
            return "exit the building"
        return f"reach {self.ref}"


class Mission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str | None = Field(default=None, max_length=600)
    objectives: list[Objective] = Field(min_length=1, max_length=8)
    mode: PlanningMode = "balanced"
    ordered: bool = True  # false lets the planner reorder up to 6 objectives
    avoid: list[str] = Field(default_factory=list, max_length=12)
    avoid_unmapped: bool = False
    allow_locked_doors: bool = False
    start_node: str | None = None
    notes: str | None = Field(default=None, max_length=400)

    def summary(self) -> str:
        return " → ".join(objective.describe() for objective in self.objectives)


class MissionError(ValueError):
    """The instruction could not be turned into something the planner can execute."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []
