"""Vision proposes bounded scene data, never executable Blender code."""

import base64
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.video import ProcessingError, extract


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Door(Contract):
    wall: Literal["front", "back", "left", "right"]
    offset: float = Field(ge=-20, le=20)
    width: float = Field(gt=0.3, le=5)
    height: float = Field(gt=0.5, le=5)
    source_frames: list[int] = Field(max_length=24)


class Furnishing(Contract):
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["sofa", "table", "chair", "cabinet", "elevator", "light"]
    x: float = Field(ge=-20, le=20)
    y: float = Field(ge=-20, le=20)
    width: float = Field(gt=0.05, le=10)
    depth: float = Field(gt=0.05, le=10)
    height: float = Field(gt=0.05, le=5)
    rotation_degrees: float = Field(ge=-180, le=180)
    source_frames: list[int] = Field(max_length=24)


class RoomPlan(Contract):
    width: float = Field(ge=1, le=30)
    depth: float = Field(ge=1, le=30)
    height: float = Field(ge=1.8, le=8)
    walls: list[Literal["front", "back", "left", "right"]] = Field(min_length=1, max_length=4)
    ceiling: bool
    doors: list[Door] = Field(max_length=12)
    furniture: list[Furnishing] = Field(max_length=40)
    assumptions: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def layout(self):
        if len(set(self.walls)) != len(self.walls):
            raise ValueError("Duplicate wall")
        for i, door in enumerate(self.doors):
            span = self.width if door.wall in {"front", "back"} else self.depth
            if (
                door.wall not in self.walls
                or abs(door.offset) + door.width / 2 > span / 2
                or door.height > self.height
            ):
                raise ValueError("Door must fit inside its wall")
            for other in self.doors[:i]:
                if (
                    other.wall == door.wall
                    and abs(other.offset - door.offset) < (other.width + door.width) / 2
                ):
                    raise ValueError("Door openings overlap")
        import math

        for item in self.furniture:
            a = math.radians(item.rotation_degrees)
            w = abs(math.cos(a)) * item.width + abs(math.sin(a)) * item.depth
            d = abs(math.sin(a)) * item.width + abs(math.cos(a)) * item.depth
            if (
                item.height > self.height
                or abs(item.x) + w / 2 > self.width / 2 + 0.1
                or abs(item.y) + d / 2 > self.depth / 2 + 0.1
            ):
                raise ValueError("Furniture extends beyond room bounds")
        return self


def plan_video(path, scan, output, settings, update, check):
    if not settings.blender_api_key or not settings.blender_planner_model:
        raise ProcessingError(
            "Automatic Blender video interpretation is not configured. Set the vision API "
            "key and model in backend settings, or upload an existing .blend / .glb model."
        )
    frames, _, decoded = extract(path, scan.video, output, "balanced", update, check)
    # Spread selected sharp views across the clip; source indices are retained.
    import numpy as np

    chosen = [
        frames[int(i)] for i in np.linspace(0, len(frames) - 1, min(16, len(frames)), dtype=int)
    ]
    content = [
        {
            "type": "input_text",
            "text": "Infer one simple room from these video frames. Return only the room JSON. "
            "Coordinates: X left/right, Y floor depth (front negative, back positive), Z up. "
            "Approximate proportions are acceptable; assume a single door leaf is 1.0668m "
            "wide only if no measured scale is available. "
            "Use only supported wall sides and observed doors/furniture. Do not invent a "
            "couch or table if absent. "
            "Elevators are furniture kind elevator, not exterior exits. Door meaning is "
            "unverified. "
            "Ceiling can be a flat approximation if seen; record assumptions. Leave "
            "unobserved walls omitted. "
            "Choose a consistent room frame, flat floor, and nonoverlapping openings. "
            "Furniture dimensions and rotation must fit inside room bounds. "
            "Source_frames must reference the supplied image indices. Explain estimated "
            "dimensions and uncertain placements in assumptions.",
        }
    ]
    for frame, _ in chosen:
        content.extend(
            [
                {"type": "input_text", "text": f"Video frame {frame}"},
                {
                    "type": "input_image",
                    "detail": "high",
                    "image_url": "data:image/jpeg;base64,"
                    + base64.b64encode((output / f"frame-{frame:06}.jpg").read_bytes()).decode(),
                },
            ]
        )
    update(
        stage="planning",
        message="Estimating walls, openings and furniture from selected views",
        progress=25,
        frames=decoded,
        keyframes=len(chosen),
        accepted=len(chosen),
    )
    payload = {
        "model": settings.blender_planner_model,
        "store": False,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "room_plan",
                "strict": True,
                "schema": RoomPlan.model_json_schema(),
            }
        },
    }
    check()
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                settings.blender_api_base.rstrip("/") + "/responses",
                headers={"Authorization": "Bearer " + settings.blender_api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        check()
        text = "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        plan = RoomPlan.model_validate_json(text)
        allowed = {f for f, _ in chosen}
        if any(f not in allowed for o in [*plan.doors, *plan.furniture] for f in o.source_frames):
            raise ValueError("Planner referenced an unavailable frame")
        return plan
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise ProcessingError(
            "Room interpretation failed validation or the vision service rejected the "
            "request. No guessed fallback model was substituted."
        ) from exc
