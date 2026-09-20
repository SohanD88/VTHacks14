/** Version 2 API contract; Y up, approximate metric depth scale. */
export type Vector3 = [number, number, number];
export type Mode = "quick" | "balanced" | "high" | "blender";
export type JobState =
  "queued" | "processing" | "completed" | "degraded" | "cancelled" | "failed";
export interface Transform {
  position: Vector3;
  rotation: Vector3;
  scale: Vector3;
}
export interface SceneObject extends Transform {
  id: string;
  label: string;
  kind: string;
  size: Vector3;
  confidence: number;
  cutaway_hidden?: boolean;
  asset_node?: string | null;
  geometry: { vertices: Vector3[]; colors: Vector3[]; triangles: Vector3[] };
  observed_geometry?: {
    vertices: Vector3[];
    colors: Vector3[];
    triangles: Vector3[];
  } | null;
  structural: boolean;
  movable: boolean;
  editable: boolean;
  entrance: boolean;
  transient: boolean;
  provenance:
    | "depth_inferred"
    | "reconstructed"
    | "primitive_fitted"
    | "semantic_asset"
    | "user_created"
    | "blender_generated";
  method: string;
  source_frames: number[];
  supporting_surface: string | null;
  relationships: string[];
  original_transform: Transform;
  modified: boolean;
  deleted: boolean;
}
export interface ScaleCalibration {
  /** Endpoints in original, uncalibrated scene coordinates. */
  reference_points: [Vector3, Vector3];
  distance_m: number;
  basis: "assumed" | "measured";
}
export interface Scene {
  preview_direction?: Vector3 | null;
  version: 2;
  asset?: { format: "glb"; data: string; sha256: string } | null;
  units: "estimated_meters";
  calibration?: ScaleCalibration | null;
  objects: SceneObject[];
  camera_path: Vector3[];
  camera_frames: number[];
  unobserved: string;
  scale_note: string;
}
export interface ScanStats {
  frames: number;
  accepted: number;
  rejected: number;
  rejection_reasons: Record<string, number>;
  keyframes: number;
  poses: number;
  pose_failures: number;
  tracking_resets: number;
  tracking_success_rate: number;
  objects: number;
  entrances: number;
  tracked_objects: number;
  duplicate_observations_merged: number;
  coverage_percent: number | null;
  coverage_description: string;
  depth_ms: number;
  semantic_ms: number;
  geometry_ms: number;
  average_frame_ms: number;
  peak_memory_mb: number;
  artifact_bytes: number;
  vertices: number;
  execution_device: string;
}
export interface ScanResponse {
  id: string;
  name: string;
  source: "video" | "capture" | "import";
  status: JobState;
  processing_mode: Mode;
  created_at: string;
  processing_ms: number;
  stage: string;
  progress: number;
  message: string;
  warnings: string[];
  error: string | null;
  scene: Scene | null;
  stats: ScanStats;
  revision: number;
  artifact_type: string;
  video: {
    filename: string;
    format: string;
    codec: string;
    width: number;
    height: number;
    fps: number;
    duration: number;
    total_frames: number;
    rotation: number;
  } | null;
  detections: { kind: string; count: number; confidence: number }[];
}
export interface ExportBundle {
  format: "spatial-scene-v2";
  scan: ScanResponse;
  original: Scene;
}
export interface HealthResponse {
  blender?: {
    available: boolean;
    video_configured: boolean;
    provider?: string;
    model?: string;
    transport: "headless" | "mcp" | "container";
  };
  status: "ok";
  processing_mode: "video-reconstruction";
  camera: { engine: string; model: string };
}
export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    request_id: string;
    fields: string[];
  };
}
export interface Layers {
  transient: boolean;
  structure: boolean;
  entrances: boolean;
  uncertain: boolean;
  path: boolean;
  labels: boolean;
  cutaway: boolean;
  observed: boolean;
}

export type RouteEndpoint =
  { point: Vector3; object_id?: never } | { object_id: string; point?: never };
export interface SceneRoute {
  scan_id: string;
  revision: number;
  polyline: Vector3[];
  distance_m: number;
  start: { point: Vector3; label: string; object_id: string | null };
  end: { point: Vector3; label: string; object_id: string | null };
  estimated: true;
  warnings: string[];
  clearance_m: number;
  cell_size: number;
}
