import type {
  ApiErrorResponse,
  ExportBundle,
  HealthResponse,
  Mode,
  ScanResponse,
  ScaleCalibration,
  Scene,
  RouteEndpoint,
  SceneRoute,
} from "../types";
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(
  /\/$/,
  "",
);
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(120000)])
        : AbortSignal.timeout(120000),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const error = body as ApiErrorResponse;
      throw new ApiError(
        error?.error?.message || `Request failed (${response.status})`,
        response.status,
        error?.error?.request_id,
      );
    }
    if (body === null)
      throw new ApiError("Unreadable API response.", response.status);
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError("Cannot reach the API. Check the backend and retry.", 0);
  }
}
export const api = {
  loadDemo: () => request<ScanResponse>("/scans/demo", { method: "POST" }),
  route: (
    id: string,
    revision: number,
    start: RouteEndpoint,
    end: RouteEndpoint,
    signal?: AbortSignal,
  ) =>
    request<SceneRoute>(`/scans/${id}/routes`, {
      method: "POST",
      body: JSON.stringify({ revision, start, end }),
      signal,
    }),
  health: (signal?: AbortSignal) =>
    request<HealthResponse>("/health", { signal }),
  list: () => request<ScanResponse[]>("/scans"),
  upload: (
    file: File,
    name: string,
    mode: Mode,
    source: "video" | "capture",
    signal?: AbortSignal,
  ) => {
    const form = new FormData();
    form.set("file", file);
    form.set("name", name);
    form.set("mode", mode);
    form.set("source", source);
    return request<ScanResponse>("/scans", {
      method: "POST",
      body: form,
      signal,
    });
  },
  getScan: (id: string) => request<ScanResponse>(`/scans/${id}`),
  status: (id: string) => request<ScanResponse>(`/scans/${id}/status`),
  cancel: (id: string) => request(`/scans/${id}/cancel`, { method: "POST" }),
  delete: (id: string) => request(`/scans/${id}`, { method: "DELETE" }),
  original: (id: string) => request<Scene>(`/scans/${id}/original`),
  save: async (
    scan: ScanResponse,
    scene: Scene,
    structural: boolean,
    confirmed = false,
  ) => {
    const changes = scene.objects
      .filter((o) => {
        const old = scan.scene?.objects.find((x) => x.id === o.id);
        return (
          !old ||
          JSON.stringify([o.position, o.rotation, o.scale, o.deleted]) !==
            JSON.stringify([old.position, old.rotation, old.scale, old.deleted])
        );
      })
      .map((o) => ({
        id: o.id,
        position: o.position,
        rotation: o.rotation,
        scale: o.scale,
        deleted: o.deleted,
      }));
    const scaleChanged =
      JSON.stringify(scene.calibration ?? null) !==
      JSON.stringify(scan.scene?.calibration ?? null);
    if (!changes.length && !scaleChanged) return { ...scan, scene };
    const result = await request<ScanResponse>(`/scans/${scan.id}/transforms`, {
      method: "PATCH",
      body: JSON.stringify({
        revision: scan.revision,
        changes,
        calibration: scene.calibration ?? null,
        structural_editing: structural,
        confirm_structural_deletion: confirmed,
      }),
    });
    return { ...result, scene };
  },
  calibrate: (scan: ScanResponse, calibration: ScaleCalibration | null) =>
    request<ScanResponse>(`/scans/${scan.id}/calibration`, {
      method: "POST",
      body: JSON.stringify({ revision: scan.revision, calibration }),
    }),
  reset: (id: string) =>
    request<ScanResponse>(`/scans/${id}/reset`, { method: "POST" }),
  export: (id: string) => request<ExportBundle>(`/scans/${id}/export`),
  import: (bundle: unknown) =>
    request<ScanResponse>("/scans/import", {
      method: "POST",
      body: JSON.stringify(bundle),
    }),
};
