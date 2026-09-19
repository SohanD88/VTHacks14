import { useEffect, useRef, useState } from "react";
import type { LiveCamera } from "../hooks/useLiveCamera";
import type { CameraSource } from "../services/liveCamera";
import {
  drawRotatedFrame,
  rotatedDimensions,
} from "../services/cameraRotation";

export function CameraFeed({
  camera,
  compact = false,
  visible = true,
}: {
  camera: LiveCamera;
  compact?: boolean;
  visible?: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const glasses = useRef<HTMLImageElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [previewSize, setPreviewSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  useEffect(() => {
    const element = video.current!;
    element.srcObject = camera.stream;
    if (camera.stream) void element.play().catch(() => {});
    return () => {
      element.srcObject = null;
    };
  }, [camera.stream]);
  useEffect(() => {
    let animationFrame = 0;
    let lastPaint = 0;
    const draw = () => {
      const container = stage.current!,
        canvas = overlay.current!;
      const rect = container.getBoundingClientRect(),
        dpr = Math.min(devicePixelRatio || 1, 2);
      const canvasWidth = Math.round(rect.width * dpr),
        canvasHeight = Math.round(rect.height * dpr);
      if (canvas.width !== canvasWidth || canvas.height !== canvasHeight) {
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
      }
      const context = canvas.getContext("2d")!;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, rect.width, rect.height);
      const sourceWidth =
        camera.source === "computer"
          ? video.current!.videoWidth
          : glasses.current?.naturalWidth || camera.frameSize?.[0] || 0;
      const sourceHeight =
        camera.source === "computer"
          ? video.current!.videoHeight
          : glasses.current?.naturalHeight || camera.frameSize?.[1] || 0;
      if (!sourceWidth || !sourceHeight || !camera.active) {
        if (camera.source === "glasses")
          setPreviewSize((previous) => (previous === null ? previous : null));
        return;
      }
      const [rotatedWidth, rotatedHeight] = rotatedDimensions(
        sourceWidth,
        sourceHeight,
        camera.rotation,
      );
      const fit = Math.min(
        rect.width / rotatedWidth,
        rect.height / rotatedHeight,
      );
      const width = rotatedWidth * fit,
        height = rotatedHeight * fit;
      const offsetX = (rect.width - width) / 2,
        offsetY = (rect.height - height) / 2;
      if (camera.source === "computer") {
        drawRotatedFrame(
          context,
          video.current!,
          sourceWidth,
          sourceHeight,
          camera.rotation,
          rect.width / 2,
          rect.height / 2,
          fit,
        );
      } else {
        const previewWidth = sourceWidth * fit,
          previewHeight = sourceHeight * fit;
        setPreviewSize((previous) =>
          previous?.width === previewWidth && previous.height === previewHeight
            ? previous
            : { width: previewWidth, height: previewHeight },
        );
      }
      context.font = `600 ${compact ? 9 : 12}px Helvetica, Arial, sans-serif`;
      for (const item of camera.detections) {
        const [left, top, right, bottom] = item.box;
        const x = offsetX + left * width,
          y = offsetY + top * height;
        context.strokeStyle = "#00d7f5";
        context.lineWidth = compact ? 1 : 2;
        context.strokeRect(
          x,
          y,
          (right - left) * width,
          (bottom - top) * height,
        );
        const label = `${item.label} ${Math.round(item.confidence * 100)}%`;
        const labelWidth = Math.min(
          rect.width,
          context.measureText(label).width + 10,
        );
        const labelX = Math.max(0, Math.min(x, rect.width - labelWidth));
        const labelY = Math.max(0, y - (compact ? 17 : 23));
        context.fillStyle = "#00d7f5";
        context.fillRect(labelX, labelY, labelWidth, compact ? 17 : 23);
        context.fillStyle = "#001014";
        context.fillText(label, labelX + 5, labelY + (compact ? 12 : 16));
      }
    };
    const observer = new ResizeObserver(draw);
    observer.observe(stage.current!);
    video.current!.addEventListener("loadedmetadata", draw);
    glasses.current?.addEventListener("load", draw);
    const image = glasses.current;
    draw();
    if (camera.source === "computer" && camera.active && visible) {
      const paint = (time: number) => {
        if (time - lastPaint >= 33) {
          draw();
          lastPaint = time;
        }
        animationFrame = requestAnimationFrame(paint);
      };
      animationFrame = requestAnimationFrame(paint);
    }
    const element = video.current!;
    return () => {
      cancelAnimationFrame(animationFrame);
      observer.disconnect();
      element.removeEventListener("loadedmetadata", draw);
      image?.removeEventListener("load", draw);
    };
  }, [
    camera.active,
    camera.source,
    camera.rotation,
    camera.frameSize,
    camera.detections,
    camera.stream,
    camera.previewUrl,
    compact,
    visible,
  ]);

  const previewStyle = {
    width: previewSize?.width ?? 0,
    height: previewSize?.height ?? 0,
    transform: `translate(-50%, -50%) rotate(${camera.rotation}deg)`,
  };

  return (
    <div className={`live-camera ${compact ? "is-compact" : ""}`}>
      <div className="camera-toolbar">
        <label className="camera-source">
          Source
          <select
            aria-label="Camera source"
            value={camera.source}
            onChange={(e) =>
              camera.selectSource(e.target.value as CameraSource)
            }
          >
            <option value="computer">Computer webcam</option>
            <option value="glasses">Glasses camera</option>
          </select>
        </label>
        <button
          className="primary-action"
          onClick={() =>
            camera.active || camera.starting
              ? camera.stop()
              : void camera.start()
          }
        >
          {camera.starting
            ? "Cancel camera"
            : camera.active
              ? "Stop camera"
              : "Start camera"}
        </button>
        <button
          className="camera-rotate"
          type="button"
          onClick={camera.rotate}
          aria-label="Rotate camera 90 degrees"
          title={`Current rotation: ${camera.rotation}°`}
        >
          <span aria-hidden="true">↻</span> Rotate 90°{" "}
          <small>{camera.rotation}°</small>
        </button>
        <span className="camera-model-state">{camera.status}</span>
      </div>
      {!compact &&
        camera.source === "computer" &&
        camera.devices.length > 1 && (
          <label className="camera-selector">
            Camera device
            <select
              aria-label="Camera device"
              value={camera.deviceId}
              onChange={(e) => void camera.start(e.target.value)}
            >
              {camera.devices.map((device, i) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Camera ${i + 1}`}
                </option>
              ))}
            </select>
          </label>
        )}
      {!compact && camera.source === "glasses" && (
        <label className="glasses-address">
          Glasses stream address
          <input
            aria-label="Glasses stream address"
            type="url"
            value={camera.glassesUrl}
            onChange={(e) => camera.setGlassesUrl(e.target.value)}
            placeholder="http://127.0.0.1:8080"
          />
        </label>
      )}
      <div
        ref={stage}
        className={compact ? "mini-feed live-stage" : "camera-feed live-stage"}
        aria-label={
          camera.active
            ? `${camera.source === "glasses" ? "Glasses" : "Computer"} live camera feed`
            : "Camera offline"
        }
      >
        <video
          ref={video}
          muted
          playsInline
          autoPlay
          style={{ display: "none" }}
        />
        {visible &&
          camera.source === "glasses" &&
          camera.active &&
          camera.previewUrl && (
            <img
              ref={glasses}
              className="glasses-video"
              style={previewStyle}
              src={camera.previewUrl}
              onError={camera.previewFailed}
              alt="Live glasses camera"
            />
          )}
        <canvas
          ref={overlay}
          className="detection-overlay"
          aria-label="Live camera and object detection bounding boxes"
          data-count={camera.detections.length}
        />
        {!camera.active && (
          <div className="camera-placeholder">
            <span className="empty-cube">◎</span>
            <strong>
              {camera.starting
                ? "Connecting camera…"
                : "Ready for a new perspective"}
            </strong>
            {!compact && (
              <p>
                Start your camera to identify common objects with live labels
                and bounding boxes.
              </p>
            )}
          </div>
        )}
      </div>
      <div className="camera-message" aria-live="polite">
        <span>{camera.sourceError || camera.message}</span>
        {(camera.status === "error" || camera.sourceError) && camera.active && (
          <button onClick={camera.retry}>Retry detection</button>
        )}
      </div>
      {!compact && (
        <div className="camera-metrics">
          <span>
            RF-DETR NANO · {camera.source === "glasses" ? "GLASSES" : "WEBCAM"}
          </span>
          <span>
            {camera.updatedAt
              ? `${camera.detections.length} visible · ${camera.processingMs ?? "—"} ms`
              : "Awaiting frame"}
          </span>
        </div>
      )}
    </div>
  );
}
