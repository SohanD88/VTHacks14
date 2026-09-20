import { useEffect, useRef, useState } from "react";
import type { Mode, ScanResponse } from "../types";
import type { LiveCamera } from "../hooks/useLiveCamera";
import { useGlassesRecorder, useRigTaps } from "../hooks/useGlassesRecorder";
import { CameraFeed } from "./CameraFeed";
import { API_BASE } from "../services/api";
import { SceneViewer } from "./SceneViewer";
interface Props {
  camera: LiveCamera;
  active: boolean;
  scan?: ScanResponse;
  recent: ScanResponse[];
  busy: boolean;
  uploading: boolean;
  loadingDemo: boolean;
  onLoadDemo(): void;
  error: string;
  health: "checking" | "online" | "offline";
  blender?: {
    available: boolean;
    video_configured: boolean;
    provider?: string;
    model?: string;
    transport: "headless" | "mcp" | "container";
  };
  onScan(
    file: File,
    name: string,
    mode: Mode,
    source: "video" | "capture",
  ): void;
  onInputChange(): void;
  onCancel(): void;
  onSelect(id: string): void;
  onDelete(id: string): void;
  onOpen(): void;
  onCheckHealth(): void;
}
export function Dashboard({
  camera,
  active,
  scan,
  recent,
  busy,
  uploading,
  loadingDemo,
  onLoadDemo,
  error,
  health,
  blender,
  onScan,
  onInputChange,
  onCancel,
  onSelect,
  onDelete,
  onOpen,
  onCheckHealth,
}: Props) {
  const detailsDialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState<File>();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("Room reconstruction");
  const mode: Mode = "blender";
  const [source, setSource] = useState<"video" | "capture">("video");
  const [inputError, setInputError] = useState("");
  const [browserRecording, setBrowserRecording] = useState(false);
  const [captureDuration, setCaptureDuration] = useState<number>();
  const [previewMeta, setPreviewMeta] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  // Glasses rig: its Arduino touch sensor (or the buttons below) starts and stops
  // recording; the finished video arrives here as the capture to reconstruct.
  const glassesRec = useGlassesRecorder(camera, (captured) => {
    setInputError("");
    setSource("capture");
    setCaptureDuration(undefined);
    onInputChange();
    setFile(captured);
  });
  const usingGlasses = camera.source === "glasses";
  const recording = browserRecording || (usingGlasses && glassesRec.recording);
  useEffect(() => {
    if (!file) {
      setUrl("");
      return;
    }
    const value = URL.createObjectURL(file);
    setUrl(value);
    setPreviewMeta("");
    return () => URL.revokeObjectURL(value);
  }, [file]);
  useEffect(
    () => () => {
      if (recorder.current?.state === "recording") recorder.current.stop();
    },
    [],
  );
  useEffect(() => {
    if (
      (camera.source !== "computer" || !camera.active) &&
      recorder.current?.state === "recording"
    ) {
      recorder.current.stop();
    }
  }, [camera.source, camera.active]);
  const choose = (file?: File) => {
    setInputError("");
    if (!file) return;
    if (!/\.(mp4|mov|webm|avi|mkv|blend|glb|json)$/i.test(file.name)) {
      setInputError(
        "Choose a video, Blender (.blend), GLB, or room-plan JSON file.",
      );
      return;
    }
    if (!file.size || file.size > 250 * 1024 ** 2) {
      setInputError("Video must be nonempty and smaller than 250 MB.");
      return;
    }
    setSource("video");
    setCaptureDuration(undefined);
    onInputChange();
    setFile(file);
  };
  const record = () => {
    try {
      if (!camera.stream) throw new Error("Start the camera first.");
      if (!window.MediaRecorder)
        throw new Error(
          "Recording is not supported by this browser. Upload a video instead.",
        );
      const mime = ["video/webm;codecs=vp9", "video/webm", "video/mp4"].find(
        (value) => MediaRecorder.isTypeSupported(value),
      );
      const value = new MediaRecorder(
        camera.stream,
        mime ? { mimeType: mime } : undefined,
      );
      const chunks: BlobPart[] = [];
      const startedAt = performance.now();
      let failed = false;
      value.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      value.onstop = () => {
        setBrowserRecording(false);
        recorder.current = null;
        const duration = (performance.now() - startedAt) / 1000;
        if (failed) return;
        if (duration < 1 || !chunks.length) {
          setInputError(
            "Recording is too short. Record for at least one second; 10–30 seconds is better for a room.",
          );
          return;
        }
        onInputChange();
        setCaptureDuration(duration);
        setSource("capture");
        setFile(
          new File(
            chunks,
            `camera-recording.${value.mimeType.includes("mp4") ? "mp4" : "webm"}`,
            { type: value.mimeType },
          ),
        );
      };
      value.onerror = () => {
        failed = true;
        setInputError("Camera recording failed. Stop and retry.");
        setBrowserRecording(false);
      };
      onInputChange();
      setFile(undefined);
      setCaptureDuration(undefined);
      value.start(500);
      recorder.current = value;
      setBrowserRecording(true);
      setInputError("");
    } catch (e) {
      setInputError((e as Error).message);
    }
  };
  // Computer webcam + Arduino: each tap on the rig's button starts or stops THIS recording.
  const tapButton = useRigTaps(camera, () => {
    if (recorder.current?.state === "recording") recorder.current.stop();
    else if (!busy) record();
  });
  const failure =
    inputError ||
    (usingGlasses ? glassesRec.error : "") ||
    error ||
    scan?.error;
  const stats = scan?.stats;
  const isModelFile = !!file && /\.(blend|glb|json)$/i.test(file.name);
  const activeSource =
    scan?.scene && scan.source !== "import" && scan.video
      ? `${API_BASE}/scans/${scan.id}/artifacts/source.${scan.video.format}`
      : "";
  return (
    <section
      className={`view dashboard-view ${active ? "is-active" : ""}`}
      aria-label="Spare dashboard"
      aria-hidden={!active}
      inert={!active}
    >
      <header className="topbar frame-corners">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="brand-wordmark">
            <h1>Spare</h1>
            <p className="brand-motto">
              Saves Lives. Saves <span>Us</span>.
            </p>
          </div>
        </div>
        <div className="dashboard-header-actions">
          <button
            className="details-trigger"
            onClick={() => detailsDialog.current?.showModal()}
          >
            Scan details ↗
          </button>
          <button
            className={`connection-state ${health}`}
            onClick={onCheckHealth}
          >
            <span className="status-dot" />
            {health === "online"
              ? "API connected"
              : health === "offline"
                ? "API offline · retry"
                : "Connecting"}
          </button>
        </div>
      </header>
      <div className="console-grid">
        <div className="console-column input-column">
          <section className="panel camera-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-index">01</span>
                <h2>Video input</h2>
              </div>
              <span className="live-badge">
                {recording
                  ? "Recording"
                  : source === "capture" && file
                    ? "Capture complete"
                    : file
                      ? "Recorded video"
                      : activeSource
                        ? "Saved video"
                        : camera.active && !camera.sourceError
                          ? "Live camera preview"
                          : "No video"}
              </span>
            </div>
            {(activeSource || (url && !isModelFile)) && (
              <>
                <video
                  className="uploaded-video"
                  src={url || activeSource}
                  poster={
                    !url && activeSource && scan?.scene?.camera_frames.length
                      ? `${API_BASE}/scans/${scan.id}/artifacts/frame-${String(scan.scene.camera_frames[0]).padStart(6, "0")}.jpg`
                      : undefined
                  }
                  controls
                  playsInline
                  onLoadedMetadata={(e) => {
                    const v = e.currentTarget;
                    setPreviewMeta(
                      `${v.videoWidth} × ${v.videoHeight} · ${
                        Number.isFinite(v.duration)
                          ? `${v.duration.toFixed(1)} seconds`
                          : captureDuration !== undefined
                            ? `${captureDuration.toFixed(1)} seconds`
                            : "Duration available after processing"
                      }`,
                    );
                  }}
                  onError={() =>
                    setPreviewMeta(
                      "Browser cannot preview this codec. Backend decoding will validate the upload.",
                    )
                  }
                />
                <p className="input-meta">
                  {url ? file?.name : scan?.video?.filename} · {previewMeta}
                </p>
              </>
            )}
            {!(activeSource || (url && !isModelFile)) && (
              <div className="video-empty">
                <span className="empty-cube">▷</span>
                <strong>Your source video</strong>
                <p>Select a video in the reconstruction workspace.</p>
              </div>
            )}
          </section>
          <section className="panel live-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-index">02</span>
                <h2>Live camera</h2>
              </div>
              <span className="live-badge">
                {camera.active ? "Live" : "Standby"}
              </span>
            </div>
            <CameraFeed
              camera={camera}
              visible={active}
              controls={
                <>
                  {camera.source === "glasses" && (
                    <p className="input-meta">
                      {glassesRec.message ||
                        (glassesRec.available
                          ? "Tap the touch sensor on the glasses, or use the recording buttons, to start and stop recording. The saved video loads here when recording stops."
                          : "Record with the glasses controls, then select the saved video above to reconstruct it.")}
                    </p>
                  )}
                  {!usingGlasses && tapButton && (
                    <p className="input-meta">
                      Arduino button connected. Tap it to start and stop
                      recording.
                    </p>
                  )}
                  <div className="capture-actions">
                    <button
                      disabled={
                        (usingGlasses
                          ? !glassesRec.available
                          : !camera.stream) ||
                        recording ||
                        busy
                      }
                      onClick={usingGlasses ? glassesRec.start : record}
                    >
                      Start recording
                    </button>
                    <button
                      disabled={!recording}
                      onClick={
                        usingGlasses
                          ? glassesRec.stop
                          : () => recorder.current?.stop()
                      }
                    >
                      Stop recording
                    </button>
                    <button
                      disabled={!file || busy || recording}
                      onClick={() => {
                        setFile(undefined);
                        setInputError("");
                      }}
                    >
                      Clear input
                    </button>
                  </div>
                </>
              }
            />
          </section>
        </div>
        <div className="console-column reconstruction-column">
          <section
            className="scan-workspace"
            aria-label="Reconstruction controls"
          >
            <div className="workspace-heading">
              <span className="eyebrow">Reconstruction workspace</span>
              <button
                type="button"
                className="prepared-demo-button"
                disabled={busy || recording || health !== "online"}
                onClick={onLoadDemo}
                title="Open the saved IMG_1343 lounge model immediately. This is a prepared demo, not a new reconstruction."
              >
                {loadingDemo ? "Loading demo…" : "Load prepared demo ↗"}
              </button>
            </div>
            <form
              className="scan-controls"
              onSubmit={(e) => {
                e.preventDefault();
                if (file && !busy) onScan(file, name, mode, source);
              }}
              aria-label="Reconstruct a video"
            >
              <label>
                Scan name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={80}
                  disabled={busy}
                />
              </label>
              <label>
                Video or Blender model
                <input
                  type="file"
                  accept="video/*,.mkv,.avi,.blend,.glb,.json"
                  onChange={(e) => choose(e.target.files?.[0])}
                  disabled={busy || recording}
                />
              </label>
              <label>
                Reconstruction
                <select defaultValue="blender" disabled={busy}>
                  <option value="blender">
                    Blender · furnished room model
                  </option>
                </select>
              </label>
              <button
                className="primary-action scan-button"
                disabled={!file || busy || recording || !name.trim()}
              >
                {uploading
                  ? "Uploading…"
                  : busy
                    ? "Processing…"
                    : failure
                      ? "Retry reconstruction"
                      : file && /\.(blend|glb|json)$/i.test(file.name)
                        ? "Open Blender model"
                        : "Reconstruct video"}
              </button>
              {busy && (
                <button type="button" onClick={onCancel}>
                  Cancel processing
                </button>
              )}
            </form>
            <div className="recent-controls">
              <label>
                Recent scans
                <select
                  value={scan?.id || ""}
                  onChange={(e) => {
                    setFile(undefined);
                    onSelect(e.target.value);
                  }}
                  disabled={busy}
                >
                  <option value="" disabled>
                    Select a saved reconstruction
                  </option>
                  {recent.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} · {s.status}
                    </option>
                  ))}
                </select>
              </label>
              {scan && !busy && (
                <button
                  onClick={() => {
                    if (
                      confirm(
                        "Delete this saved scan and its diagnostic files?",
                      )
                    )
                      onDelete(scan.id);
                  }}
                >
                  Delete saved scan
                </button>
              )}
            </div>
            <div
              className={`scan-feedback ${failure ? "has-error" : ""}`}
              role={failure ? "alert" : "status"}
              aria-live="polite"
            >
              {failure ||
                (uploading
                  ? "Uploading selected file…"
                  : recording
                    ? usingGlasses
                      ? `Recording on the glasses · ${Math.round(glassesRec.elapsed)} s`
                      : "Recording camera…"
                    : scan
                      ? `${scan.status} · ${scan.stage.replaceAll("_", " ")} · ${scan.message}`
                      : file
                        ? `${source === "capture" ? "Capture complete" : isModelFile ? "Blender model import" : "Uploaded-video mode"} · ready to process`
                        : "No input selected. Upload a video, Blender model, or record your camera.")}
              {scan && <span> Scan {scan.id.slice(0, 8)}</span>}
            </div>
            {scan && (
              <div className="job-progress">
                <progress value={scan.progress} max={100} />
                <span>
                  {Math.round(scan.progress)}%
                  {scan.stage === "finished" ? " · Ready" : ""}
                </span>
              </div>
            )}
          </section>
          <section className="panel environment-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-index">03</span>
                <h2>3D environment</h2>
              </div>
              <span className="muted">
                {scan?.status === "degraded"
                  ? "Partial / uncertain"
                  : scan?.status || "Awaiting scan"}
              </span>
            </div>
            <SceneViewer
              scene={scan?.scene}
              active={active}
              mode="preview"
              emptyMessage={
                busy
                  ? "Your 3D model will appear when processing finishes."
                  : file
                    ? "Click Reconstruct video to generate your 3D model."
                    : undefined
              }
              onOpen={onOpen}
            />
            <button
              className="open-cue"
              aria-label="Open the full 3D modeling environment"
              disabled={busy || (!!file && !scan?.scene)}
              onClick={onOpen}
            >
              Enter Sandbox ↗
            </button>
          </section>
        </div>
      </div>
      <dialog
        ref={detailsDialog}
        className="scan-details-dialog"
        aria-labelledby="scan-details-title"
        onClick={(event) => {
          if (event.target === event.currentTarget)
            detailsDialog.current?.close();
        }}
      >
        <div className="details-dialog-heading">
          <h2 id="scan-details-title">Scan details</h2>
          <button
            onClick={() => detailsDialog.current?.close()}
            aria-label="Close scan details"
          >
            Close ×
          </button>
        </div>
        <div className="scan-details-content">
          {scan?.video && (
            <details className="source-details">
              <summary>Video details</summary>
              <p className="input-meta">
                Active scan: {scan.video.filename} · {scan.video.width} ×{" "}
                {scan.video.height} · {scan.video.codec} ·{" "}
                {scan.video.fps.toFixed(1)} fps ·{" "}
                {scan.video.duration.toFixed(1)}s
              </p>
            </details>
          )}

          {mode === "blender" && blender && (
            <p className="input-meta">
              {!blender.available
                ? "Blender is not configured on this server."
                : !blender.video_configured
                  ? "Blender model import is ready. New video generation needs a vision API key and model configured on the server."
                  : `${blender.model || "Vision model"} → Blender is ready. Selected video frames are sent to ${blender.provider === "gemini" ? "Google Gemini" : "the configured vision service"}.`}
            </p>
          )}
          <div className="scan-details-grid">
            <section
              className="panel detections-panel"
              data-testid="scan-detections"
            >
              <div className="panel-heading">
                <h2>Reconstructed elements</h2>
                <span>{stats?.entrances ?? 0} opening candidates</span>
              </div>
              <div className="detection-list">
                {scan?.detections.length ? (
                  scan.detections.map((d) => (
                    <div key={d.kind}>
                      <span className="object-icon" />
                      <strong className="capitalize">{d.kind}</strong>
                      <em>{d.count}</em>
                      <div />
                      <b>{Math.round(d.confidence * 100)}%</b>
                    </div>
                  ))
                ) : (
                  <p className="empty-copy">
                    Scene labels appear after reconstruction.
                  </p>
                )}
              </div>
              {
                <div data-testid="live-detections" className="live-separate">
                  Live preview only:{" "}
                  {!camera.active
                    ? "Camera offline"
                    : camera.sourceError ||
                      (!camera.detections.length
                        ? camera.updatedAt
                          ? "No supported objects in this frame."
                          : "Waiting for live detection results…"
                        : "")}
                  {camera.detections.map((d, i) => (
                    <span key={i}>
                      {d.label} {Math.round(d.confidence * 100)}%{" "}
                    </span>
                  ))}
                </div>
              }
            </section>
            <section className="panel spatial-panel">
              <div className="panel-heading">
                <h2>Processing measurements</h2>
              </div>
              <div className="model-stats">
                {[
                  ["Objects", stats?.objects],
                  ["Decoded frames", stats?.frames],
                  [
                    "Accepted / rejected",
                    stats ? `${stats.accepted} / ${stats.rejected}` : undefined,
                  ],
                  ["Keyframes", stats?.keyframes],
                  [
                    "Camera poses",
                    stats ? `${stats.poses} / ${stats.keyframes}` : undefined,
                  ],
                  ["Tracking failures", stats?.pose_failures],
                  [
                    "Duration",
                    scan
                      ? `${(scan.processing_ms / 1000).toFixed(1)}s`
                      : undefined,
                  ],
                  [
                    "Artifact",
                    stats
                      ? `${(stats.artifact_bytes / 1024 ** 2).toFixed(2)} MB`
                      : undefined,
                  ],
                ].map(([label, value]) => (
                  <article key={label}>
                    <span>{label}</span>
                    <strong
                      data-testid={
                        label === "Objects" ? "object-count" : undefined
                      }
                    >
                      {value ?? "—"}
                    </strong>
                  </article>
                ))}
              </div>
              <p className="input-meta">
                {stats?.coverage_description ||
                  "Coverage is unknown until observations are processed."}
              </p>
            </section>
          </div>
          {scan?.warnings.length ? (
            <aside className="quality-notes">
              <h2>Reconstruction notes</h2>
              <ul>
                {scan.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </aside>
          ) : null}
        </div>
      </dialog>
    </section>
  );
}
