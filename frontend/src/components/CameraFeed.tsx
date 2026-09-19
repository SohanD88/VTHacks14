import { useEffect, useRef } from 'react';
import type { LiveCamera } from '../hooks/useLiveCamera';

export function CameraFeed({ camera, compact = false }: { camera: LiveCamera; compact?: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = video.current!;
    element.srcObject = camera.stream;
    if (camera.stream) void element.play().catch(() => {});
    return () => { element.srcObject = null; };
  }, [camera.stream]);
  useEffect(() => {
    const draw = () => {
      const container = stage.current!, canvas = overlay.current!, element = video.current!;
      const rect = container.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
      const context = canvas.getContext('2d')!;
      context.scale(dpr, dpr);
      if (!element.videoWidth || !camera.stream) return;
      const fit = Math.min(rect.width / element.videoWidth, rect.height / element.videoHeight);
      const width = element.videoWidth * fit, height = element.videoHeight * fit;
      const offsetX = (rect.width - width) / 2, offsetY = (rect.height - height) / 2;
      context.font = `600 ${compact ? 9 : 12}px Helvetica, Arial, sans-serif`;
      for (const item of camera.detections) {
        const [left, top, right, bottom] = item.box;
        const x = offsetX + left * width, y = offsetY + top * height;
        context.strokeStyle = '#00d7f5'; context.lineWidth = compact ? 1 : 2;
        context.strokeRect(x, y, (right - left) * width, (bottom - top) * height);
        const label = `${item.label} ${Math.round(item.confidence * 100)}%`;
        const labelWidth = Math.min(rect.width, context.measureText(label).width + 10);
        const labelX = Math.max(0, Math.min(x, rect.width - labelWidth));
        const labelY = Math.max(0, y - (compact ? 17 : 23));
        context.fillStyle = '#00d7f5'; context.fillRect(labelX, labelY, labelWidth, compact ? 17 : 23);
        context.fillStyle = '#001014'; context.fillText(label, labelX + 5, labelY + (compact ? 12 : 16));
      }
    };
    const observer = new ResizeObserver(draw);
    observer.observe(stage.current!);
    video.current!.addEventListener('loadedmetadata', draw);
    draw();
    const element = video.current!;
    return () => { observer.disconnect(); element.removeEventListener('loadedmetadata', draw); };
  }, [camera.detections, camera.stream, compact]);

  return <div className={`live-camera ${compact ? 'is-compact' : ''}`}>
    <div className="camera-toolbar">
      <button className="primary-action" onClick={() => camera.stream || camera.starting ? camera.stop() : void camera.start()}>
        {camera.starting ? 'Cancel camera' : camera.stream ? 'Stop camera' : 'Start camera'}
      </button>
      {!compact && camera.devices.length > 1 && <label className="camera-selector">Camera<select aria-label="Camera device" value={camera.deviceId} onChange={e => void camera.start(e.target.value)}>{camera.devices.map((device, i) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${i + 1}`}</option>)}</select></label>}
      <span className="camera-model-state">{camera.status}</span>
    </div>
    <div ref={stage} className={compact ? 'mini-feed live-stage' : 'camera-feed live-stage'} aria-label={camera.stream ? 'Live camera feed' : 'Camera offline'}>
      <video ref={video} muted playsInline autoPlay />
      <canvas ref={overlay} className="detection-overlay" aria-label="Object detection bounding boxes" data-count={camera.detections.length} />
      {!camera.stream && <div className="camera-placeholder"><span className="empty-cube">◎</span><strong>{camera.starting ? 'Connecting camera…' : 'Ready for a new perspective'}</strong>{!compact && <p>Start your camera to identify common objects with live labels and bounding boxes.</p>}</div>}
    </div>
    <div className="camera-message" aria-live="polite"><span>{camera.message}</span>{camera.status === 'error' && camera.stream && <button onClick={camera.retry}>Retry detection</button>}</div>
    {!compact && <div className="camera-metrics"><span>RF-DETR NANO</span><span>{camera.updatedAt ? `${camera.detections.length} visible · ${camera.processingMs ?? '—'} ms` : 'Awaiting frame'}</span></div>}
  </div>;
}
