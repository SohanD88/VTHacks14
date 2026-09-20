"""Versioned, finite, bounded scene and processing contracts (Y up, estimated meters)."""

from datetime import datetime, timezone
from math import dist
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False, ge=-10000, le=10000)]
Vector3 = tuple[Finite, Finite, Finite]
Positive = Annotated[float, Field(gt=0, le=10000, allow_inf_nan=False)]
Mode = Literal["quick", "balanced", "high", "blender"]
State = Literal["queued", "processing", "completed", "degraded", "cancelled", "failed"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Transform(Contract):
    position: Vector3 = (0, 0, 0)
    rotation: Vector3 = (0, 0, 0)
    scale: tuple[Positive, Positive, Positive] = (1, 1, 1)


class Geometry(Contract):
    vertices: list[Vector3] = Field(default_factory=list, max_length=300000)
    colors: list[tuple[float, float, float]] = Field(default_factory=list, max_length=300000)
    triangles: list[tuple[int, int, int]] = Field(default_factory=list, max_length=600000)

    @model_validator(mode="after")
    def valid_geometry(self):
        if len(self.colors) != len(self.vertices):
            raise ValueError("Every vertex must have a color")
        if any(not all(0 <= c <= 1 for c in color) for color in self.colors):
            raise ValueError("Colors must be normalized")
        if any(not all(0 <= i < len(self.vertices) for i in face) for face in self.triangles):
            raise ValueError("Invalid triangle index")
        return self


class ModelAsset(Contract):
    """Embedded GLB keeps original and edited exports portable and self-contained."""

    format: Literal["glb"] = "glb"
    data: str = Field(max_length=22_000_000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_asset(self):
        from app.services.glb import validate_asset

        validate_asset(self.data, self.sha256)
        return self


class SceneObject(Contract):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(max_length=150)
    kind: str = Field(max_length=80)
    confidence: float = Field(ge=0, le=1)
    cutaway_hidden: bool = False
    asset_node: str | None = Field(default=None, max_length=100)
    position: Vector3
    rotation: Vector3 = (0, 0, 0)
    scale: tuple[Positive, Positive, Positive] = (1, 1, 1)
    size: tuple[Positive, Positive, Positive]
    geometry: Geometry = Field(default_factory=Geometry)
    observed_geometry: Geometry | None = None
    structural: bool = False
    movable: bool = True
    editable: bool = True
    entrance: bool = False
    transient: bool = False
    provenance: Literal[
        "depth_inferred",
        "reconstructed",
        "primitive_fitted",
        "semantic_asset",
        "user_created",
        "blender_generated",
    ] = "depth_inferred"
    method: str = "metric depth + semantic segmentation + RGB-D tracking"
    source_frames: list[int] = Field(default_factory=list, max_length=500)
    supporting_surface: str | None = None
    relationships: list[str] = Field(default_factory=list)
    original_transform: Transform
    modified: bool = False
    deleted: bool = False


class ScaleCalibration(Contract):
    """Reference endpoints in the original, uncalibrated scene coordinate system."""

    reference_points: tuple[Vector3, Vector3]
    distance_m: float = Field(gt=0, le=1000, allow_inf_nan=False)
    basis: Literal["assumed", "measured"] = "assumed"

    @property
    def factor(self) -> float:
        return self.distance_m / dist(*self.reference_points)

    @model_validator(mode="after")
    def usable_reference(self):
        if dist(*self.reference_points) < 0.01:
            raise ValueError("Choose two distinct reference points at least 1 cm apart")
        if not 0.05 <= self.factor <= 20:
            raise ValueError("Scale correction must be between 0.05 and 20; check the reference")
        return self


class CalibrationEdit(Contract):
    revision: int = Field(ge=0)
    calibration: ScaleCalibration | None


class Scene(Contract):
    version: Literal[2] = 2
    asset: ModelAsset | None = None
    preview_direction: Vector3 | None = None
    units: Literal["estimated_meters"] = "estimated_meters"
    calibration: ScaleCalibration | None = None
    objects: list[SceneObject] = Field(default_factory=list, max_length=2000)
    camera_path: list[Vector3] = Field(default_factory=list, max_length=500)
    camera_frames: list[int] = Field(default_factory=list, max_length=500)
    unobserved: str = "Empty areas have not been reconstructed; room completeness is unknown."
    scale_note: str = (
        "Monocular metric depth and assumed camera intrinsics; not survey measurements."
    )

    @model_validator(mode="after")
    def unique_ids(self):
        if self.preview_direction is not None and sum(v * v for v in self.preview_direction) < 1e-8:
            raise ValueError("Preview direction must be nonzero")
        if len({o.id for o in self.objects}) != len(self.objects):
            raise ValueError("Object IDs must be unique")
        if (
            sum(
                len(o.geometry.vertices)
                + (len(o.observed_geometry.vertices) if o.observed_geometry else 0)
                for o in self.objects
            )
            > 500000
        ):
            raise ValueError("Scene exceeds geometry budget")
        if self.asset:
            from app.services.glb import asset_node_ids

            ids = asset_node_ids(self.asset.data)
            refs = [o.asset_node for o in self.objects]
            if any(ref is None for ref in refs) or len(set(refs)) != len(refs):
                raise ValueError("GLB objects need unique node references")
            if set(refs) != ids:
                raise ValueError("GLB nodes and scene objects must match")
        elif any(o.asset_node for o in self.objects):
            raise ValueError("Object references a missing GLB asset")
        return self


class VideoMetadata(Contract):
    filename: str
    format: str
    codec: str
    width: int
    height: int
    fps: float
    duration: float
    total_frames: int
    rotation: int = 0


class ScanStats(Contract):
    frames: int = 0
    accepted: int = 0
    rejected: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    keyframes: int = 0
    poses: int = 0
    pose_failures: int = 0
    tracking_resets: int = 0
    tracking_success_rate: float = 0
    objects: int = 0
    entrances: int = 0
    tracked_objects: int = 0
    duplicate_observations_merged: int = 0
    coverage_percent: float | None = None
    coverage_description: str = "Room coverage cannot be measured without a complete reference map."
    depth_ms: int = 0
    semantic_ms: int = 0
    geometry_ms: int = 0
    average_frame_ms: float = 0
    peak_memory_mb: float = 0
    artifact_bytes: int = 0
    vertices: int = 0
    execution_device: str = "pending"


class ScanResponse(Contract):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    source: Literal["video", "capture", "import"] = "video"
    status: State = "queued"
    processing_mode: Mode = "balanced"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processing_ms: int = 0
    stage: str = "queued"
    progress: float = Field(default=0, ge=0, le=100)
    message: str = "Waiting for worker"
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    video: VideoMetadata | None = None
    scene: Scene | None = None
    detections: list[dict] = Field(default_factory=list)
    stats: ScanStats = Field(default_factory=ScanStats)
    revision: int = 0
    artifact_type: str = "semantic triangle mesh JSON + PLY"


class SceneEdit(Contract):
    revision: int = Field(ge=0)
    scene: Scene
    structural_editing: bool = False
    confirm_structural_deletion: bool = False


class CameraHealth(BaseModel):
    engine: Literal["rf-detr-nano"] = "rf-detr-nano"
    model: Literal["unloaded", "loading", "ready", "error"] = "unloaded"


class BlenderHealth(BaseModel):
    provider: str = ""
    model: str = ""
    available: bool = False
    video_configured: bool = False
    transport: Literal["headless", "mcp", "container"] = "headless"


class HealthResponse(BaseModel):
    blender: BlenderHealth = Field(default_factory=BlenderHealth)
    camera: CameraHealth = Field(default_factory=CameraHealth)
    status: Literal["ok"] = "ok"
    service: str = "spatial-intelligence-api"
    processing_mode: Literal["video-reconstruction"] = "video-reconstruction"


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[str] = []


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ObjectTransformEdit(Transform):
    id: str = Field(min_length=1, max_length=100)
    deleted: bool = False


class TransformEdits(Contract):
    revision: int = Field(ge=0)
    changes: list[ObjectTransformEdit] = Field(default_factory=list, max_length=2000)
    calibration: ScaleCalibration | None = None
    structural_editing: bool = False
    confirm_structural_deletion: bool = False
