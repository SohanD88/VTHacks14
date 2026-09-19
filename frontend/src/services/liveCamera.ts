import { API_BASE } from './api';

export interface LiveDetection { label: string; confidence: number; box: [number, number, number, number] }
export interface CameraState {
  stream: MediaStream | null;
  starting: boolean;
  status: 'standby' | 'connecting' | 'loading' | 'ready' | 'reconnecting' | 'error';
  message: string;
  detections: LiveDetection[];
  devices: MediaDeviceInfo[];
  deviceId: string;
  updatedAt: number | null;
  processingMs: number | null;
}
const initialState = (): CameraState => ({ stream: null, starting: false, status: 'standby', message: 'Connect a camera to detect objects.', detections: [], devices: [], deviceId: '', updatedAt: null, processingMs: null });

/** One camera stream and one inference connection shared by both app views. */
export class LiveCameraSession {
  private state = initialState();
  private listeners = new Set<() => void>();
  private video = document.createElement('video');
  private canvas = document.createElement('canvas');
  private socket: WebSocket | null = null;
  private generation = 0;
  private frameId = 0;
  private pendingId: number | null = null;
  private sendTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private pendingTimer?: ReturnType<typeof setTimeout>;
  private readyTimer?: ReturnType<typeof setTimeout>;
  private fatal = false;

  constructor() { this.video.muted = true; this.video.playsInline = true; }
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(patch: Partial<CameraState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach(listener => listener());
  }
  private clearPending() { this.pendingId = null; clearTimeout(this.pendingTimer); }
  stop = () => {
    this.generation++;
    clearInterval(this.sendTimer); clearTimeout(this.reconnectTimer); clearTimeout(this.readyTimer);
    this.clearPending();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.state.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    this.video.srcObject = null;
    this.fatal = false;
    this.update(initialState());
  };
  start = async (deviceId?: string) => {
    this.stop();
    const generation = this.generation;
    this.update({ starting: true, message: 'Requesting camera permission…' });
    let stream: MediaStream | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS.');
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: deviceId ? { deviceId: { exact: deviceId } } : true });
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
      this.video.srcObject = stream;
      await this.video.play();
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
      this.update({ stream, starting: false, status: 'connecting', message: 'Camera active. Connecting to detection server…', deviceId: stream.getVideoTracks()[0]?.getSettings().deviceId || '' });
      stream.getVideoTracks().forEach(track => { track.onended = () => { this.stop(); this.update({ status: 'error', message: 'Camera disconnected. Reconnect it and start again.' }); }; });
      void this.refreshDevices(generation);
      this.connect();
      this.sendTimer = setInterval(() => this.sendFrame(), 333);
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      if (generation !== this.generation) return;
      this.stop();
      const message = error instanceof Error ? error.message : 'Unknown camera error';
      this.update({ status: 'error', message: `Camera unavailable: ${message}` });
    }
  };
  private async refreshDevices(generation: number) {
    try {
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'videoinput');
      if (generation === this.generation) this.update({ devices });
    } catch { /* Capture can still work when device enumeration is unavailable. */ }
  }
  retry = () => {
    if (!this.state.stream) { void this.start(); return; }
    this.fatal = false;
    clearTimeout(this.reconnectTimer); clearTimeout(this.readyTimer);
    const old = this.socket; this.socket = null; old?.close(); this.clearPending();
    this.connect();
  };
  private connect() {
    if (!this.state.stream || this.socket || this.fatal) return;
    const url = new URL(`${API_BASE}/camera/detect`, window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url);
    this.socket = socket;
    this.update({ status: 'connecting' });
    this.readyTimer = setTimeout(() => {
      if (this.socket !== socket || this.state.status === 'ready') return;
      this.fatal = true;
      this.update({ status: 'error', message: 'Model initialization timed out. Check the backend, then retry detection.' });
      socket.close();
    }, 180000);
    socket.onopen = () => {
      if (this.socket === socket) this.update({ status: 'loading', message: 'Loading RF-DETR Nano. The first run downloads model weights…' });
    };
    socket.onmessage = event => {
      if (this.socket !== socket) return;
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.type === 'status') {
        if (data.status === 'ready') {
          clearTimeout(this.readyTimer);
          this.update({ status: 'ready', message: 'Detection ready. Hold up a common object.' });
        } else this.update({ status: 'loading' });
      } else if (data.type === 'detections' && data.id === this.pendingId) {
        this.clearPending();
        const detections = Array.isArray(data.detections) ? data.detections.filter(isDetection) : [];
        this.update({ detections, updatedAt: Date.now(), processingMs: data.processing_ms ?? null,
          message: detections.length ? `${detections.length} ${detections.length === 1 ? 'object' : 'objects'} in the latest frame.` : 'No supported objects in this frame.' });
      } else if (data.type === 'error') {
        this.clearPending();
        this.fatal = data.fatal === true;
        if (this.fatal) clearTimeout(this.readyTimer);
        this.update({ detections: [], updatedAt: null, status: this.fatal ? 'error' : this.state.status, message: data.message || 'Detection failed.' });
      }
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null; this.clearPending(); clearTimeout(this.readyTimer);
      this.update({ detections: [], updatedAt: null, processingMs: null });
      if (this.state.stream && !this.fatal) {
        this.update({ status: 'reconnecting', message: 'Detection server disconnected. Retrying…' });
        this.reconnectTimer = setTimeout(() => this.connect(), 2000);
      }
    };
    socket.onerror = () => { if (this.socket === socket && !this.fatal) this.update({ message: 'Cannot reach the detection server. Retrying…' }); };
  }
  private sendFrame() {
    const socket = this.socket;
    if (!this.state.stream || this.state.status !== 'ready' || this.pendingId !== null || socket?.readyState !== WebSocket.OPEN || !this.video.videoWidth) return;
    const ratio = Math.min(1, 640 / this.video.videoWidth);
    const width = this.canvas.width = Math.max(1, Math.round(this.video.videoWidth * ratio));
    const height = this.canvas.height = Math.max(1, Math.round(this.video.videoHeight * ratio));
    this.canvas.getContext('2d')!.drawImage(this.video, 0, 0, width, height);
    const id = ++this.frameId;
    this.pendingId = id;
    this.canvas.toBlob(blob => {
      if (this.socket !== socket || !this.state.stream || this.pendingId !== id) return;
      if (!blob || socket.readyState !== WebSocket.OPEN) { this.clearPending(); return; }
      socket.send(JSON.stringify({ type: 'frame', id, width, height }));
      socket.send(blob);
      this.pendingTimer = setTimeout(() => { if (this.pendingId === id) socket.close(); }, 12000);
    }, 'image/jpeg', .75);
  }
}

function isDetection(value: unknown): value is LiveDetection {
  if (!value || typeof value !== 'object') return false;
  const item = value as LiveDetection;
  return typeof item.label === 'string' && Number.isFinite(item.confidence) && item.confidence >= 0 && item.confidence <= 1 && Array.isArray(item.box) && item.box.length === 4 && item.box.every(n => Number.isFinite(n) && n >= 0 && n <= 1) && item.box[2] > item.box[0] && item.box[3] > item.box[1];
}
