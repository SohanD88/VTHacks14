from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Vector3 = tuple[float, float, float]
Positive = Annotated[float, Field(gt=0)]
Preset = Literal["office", "corridor"]


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    preset: Preset = "office"
    source: Literal["demo"] = "demo"


class SceneObject(BaseModel):
    id: str
    label: str
    kind: Literal["desk", "chair", "door", "cabinet", "person"]
    position: Vector3  # Center, in meters. Y is up.
    size: tuple[Positive, Positive, Positive]
    confidence: float = Field(ge=0, le=1)


class Room(BaseModel):
    id: str
    name: str
    center: Vector3
    size: tuple[Positive, Positive, Positive]


class Scene(BaseModel):
    units: Literal["meters"] = "meters"
    rooms: list[Room]
    objects: list[SceneObject]
    camera_path: list[Vector3]


class Detection(BaseModel):
    kind: str
    count: int
    confidence: float


class ScanStats(BaseModel):
    rooms_mapped: int
    objects: int
    frames: int
    keyframes: int
    coverage_percent: int = Field(ge=0, le=100)


class ScanResponse(BaseModel):
    id: UUID
    name: str
    preset: Preset
    source: Literal["demo"] = "demo"
    status: Literal["completed"] = "completed"
    processing_mode: Literal["mock"] = "mock"
    created_at: datetime
    processing_ms: int
    message: str
    scene: Scene
    detections: list[Detection]
    stats: ScanStats


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "spatial-intelligence-api"
    processing_mode: Literal["mock"] = "mock"


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[str] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail
