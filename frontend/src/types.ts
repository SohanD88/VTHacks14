/** Mirrors backend/app/schemas.py. Scene coordinates use meters; Y is up. */
export type Vector3 = [number, number, number];
export type Preset = 'office' | 'corridor';
export interface ScanRequest { name: string; preset: Preset; source: 'demo' }
export interface SceneObject {
  id: string;
  label: string;
  kind: 'desk' | 'chair' | 'door' | 'cabinet' | 'person';
  position: Vector3;
  size: Vector3;
  confidence: number;
}
export interface Scene {
  units: 'meters';
  rooms: { id: string; name: string; center: Vector3; size: Vector3 }[];
  objects: SceneObject[];
  camera_path: Vector3[];
}
export interface ScanResponse {
  id: string;
  name: string;
  preset: Preset;
  source: 'demo';
  status: 'completed';
  processing_mode: 'mock';
  created_at: string;
  processing_ms: number;
  message: string;
  scene: Scene;
  detections: { kind: string; count: number; confidence: number }[];
  stats: { rooms_mapped: number; objects: number; frames: number; keyframes: number; coverage_percent: number };
}
export interface HealthResponse {
  status: 'ok'; service: string; processing_mode: 'mock';
  camera: { engine: 'rf-detr-nano'; model: 'unloaded' | 'loading' | 'ready' | 'error' };
}
export interface ApiErrorResponse { error: { code: string; message: string; request_id: string; fields: string[] } }
