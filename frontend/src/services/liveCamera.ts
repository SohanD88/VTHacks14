import { API_BASE } from './api';
import { drawRotatedFrame, rotatedDimensions, type CameraRotation } from './cameraRotation';

export type CameraSource = 'computer' | 'glasses';
export interface LiveDetection { label: string; confidence: number; box: [number, number, number, number] }
export interface CameraState {
  source: CameraSource;
  rotation: CameraRotation;
  active: boolean;
  stream: MediaStream | null;
  glassesUrl: string;
  previewUrl: string | null;
  sourceError: string;
  frameSize: [number, number] | null;
  starting: boolean;
  status: 'standby' | 'connecting' | 'loading' | 'ready' | 'reconnecting' | 'error';
  message: string;
  detections: LiveDetection[];
  devices: MediaDeviceInfo[];
  deviceId: string;
  updatedAt: number | null;
  processingMs: number | null;
}

const GLASSES_URL_KEY = 'spatial-glasses-url';
const DEFAULT_GLASSES_URL = 'http://127.0.0.1:8080';
function savedGlassesUrl(): string {
  try { return localStorage.getItem(GLASSES_URL_KEY) || DEFAULT_GLASSES_URL; }
  catch { return DEFAULT_GLASSES_URL; }
}
function initialState(): CameraState {
  return { source: 'computer', rotation: 0, active: false, stream: null, glassesUrl: savedGlassesUrl(),
    previewUrl: null, sourceError: '', frameSize: null, starting: false, status: 'standby',
    message: 'Connect a camera to detect objects.', detections: [], devices: [], deviceId: '',
    updatedAt: null, processingMs: null };
}
function glassesBaseUrl(value: string): string {
  const url = new URL(value.trim());
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Enter a glasses address starting with http:// or https://.');
  }
  return url.origin;
}

/** One selected source and one inference connection shared by both app views. */
export class LiveCameraSession {
  private state = initialState();
  private listeners = new Set<() => void>();
  private video = document.createElement('video');
  private canvas = document.createElement('canvas');
  private socket: WebSocket | null = null;
  private frameAbort: AbortController | null = null;
  private generation = 0;
  private frameId = 0;
  private pendingId: number | null = null;
  private pendingRotation: CameraRotation | null = null;
  private capturing = false;
  private glassesBase = '';
  private nextGlassesAttempt = 0;
  private sendTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private previewTimer?: ReturnType<typeof setTimeout>;
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
  private clearPending() { this.pendingId = null; this.pendingRotation = null; clearTimeout(this.pendingTimer); }
  stop = () => {
    this.generation++;
    clearInterval(this.sendTimer); clearTimeout(this.reconnectTimer); clearTimeout(this.previewTimer);
    clearTimeout(this.readyTimer); this.clearPending();
    this.frameAbort?.abort(); this.frameAbort = null;
    const socket = this.socket; this.socket = null; socket?.close();
    this.state.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    this.video.srcObject = null;
    this.glassesBase = ''; this.capturing = false; this.fatal = false;
    this.update({ ...initialState(), source: this.state.source, rotation: this.state.rotation, glassesUrl: this.state.glassesUrl,
      devices: this.state.devices, deviceId: this.state.deviceId });
  };
  rotate = () => {
    const rotation = ((this.state.rotation + 90) % 360) as CameraRotation;
    this.update({ rotation, detections: [], updatedAt: null, processingMs: null });
  };
  selectSource = (source: CameraSource) => {
    if (source === this.state.source) return;
    const wasRunning = this.state.active || this.state.starting;
    this.stop();
    this.update({ source, message: source === 'glasses' ? 'Start the glasses camera stream.' : 'Start your computer webcam.' });
    if (wasRunning) void this.start();
  };
  setGlassesUrl = (value: string) => {
    if (value === this.state.glassesUrl) return;
    if (this.state.source === 'glasses' && (this.state.active || this.state.starting)) this.stop();
    this.update({ glassesUrl: value, message: 'Start the glasses camera with this address.' });
    try { localStorage.setItem(GLASSES_URL_KEY, value); } catch { /* Storage is optional. */ }
  };
  start = async (deviceId?: string) => {
    this.stop();
    const generation = this.generation;
    this.update({ starting: true, message: this.state.source === 'computer' ? 'Requesting camera permission…' : 'Connecting to glasses camera…' });
    if (this.state.source === 'glasses') {
      try {
        this.glassesBase = glassesBaseUrl(this.state.glassesUrl);
        this.update({ active: true, starting: false, previewUrl: `${this.glassesBase}/stream?session=${generation}`,
          status: 'connecting', message: 'Connecting to glasses stream and detection server…' });
        this.connect();
        this.sendTimer = setInterval(() => void this.sendFrame(), 333);
      } catch {
        this.update({ starting: false, status: 'error', message: 'Enter a valid glasses address, such as http://127.0.0.1:8080.' });
      }
      return;
    }
    let stream: MediaStream | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS.');
      const selected = deviceId || this.state.deviceId;
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: selected ? { deviceId: { exact: selected } } : true });
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
      this.video.srcObject = stream;
      await this.video.play();
      if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
      this.update({ stream, active: true, starting: false, status: 'connecting',
        message: 'Camera active. Connecting to detection server…',
        deviceId: stream.getVideoTracks()[0]?.getSettings().deviceId || '' });
      stream.getVideoTracks().forEach(track => { track.onended = () => { this.stop(); this.update({ status: 'error', message: 'Camera disconnected. Reconnect it and start again.' }); }; });
      void this.refreshDevices(generation);
      this.connect();
      this.sendTimer = setInterval(() => void this.sendFrame(), 333);
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
    if (!this.state.active) { void this.start(); return; }
    this.fatal = false;
    this.nextGlassesAttempt = 0;
    clearTimeout(this.reconnectTimer); clearTimeout(this.readyTimer); clearTimeout(this.previewTimer);
    const old = this.socket; this.socket = null; old?.close(); this.clearPending();
    if (this.state.source === 'glasses') this.update({ sourceError: '', previewUrl: `${this.glassesBase}/stream?retry=${Date.now()}` });
    this.connect();
  };
  previewFailed = () => {
    if (this.state.source !== 'glasses' || !this.state.active) return;
    this.update({ sourceError: 'Glasses stream unavailable. Check that tap_stream.py is running.',
      detections: [], updatedAt: null, processingMs: null });
    clearTimeout(this.previewTimer);
    const generation = this.generation;
    this.previewTimer = setTimeout(() => {
      if (generation === this.generation && this.state.active) this.update({ previewUrl: `${this.glassesBase}/stream?retry=${Date.now()}` });
    }, 2000);
  };
  private connect() {
    if (!this.state.active || this.socket || this.fatal) return;
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
        const matchesRotation = this.pendingRotation === this.state.rotation;
        this.clearPending();
        if (!matchesRotation) return;
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
      if (this.state.active && !this.fatal) {
        this.update({ status: 'reconnecting', message: 'Detection server disconnected. Retrying…' });
        this.reconnectTimer = setTimeout(() => this.connect(), 2000);
      }
    };
    socket.onerror = () => { if (this.socket === socket && !this.fatal) this.update({ message: 'Cannot reach the detection server. Retrying…' }); };
  }
  private async sendFrame() {
    const socket = this.socket;
    if (!this.state.active || this.state.status !== 'ready' || this.pendingId !== null ||
        this.capturing || socket?.readyState !== WebSocket.OPEN) return;
    if (this.state.source === 'glasses' && Date.now() < this.nextGlassesAttempt) return;
    const generation = this.generation;
    const rotation = this.state.rotation;
    this.capturing = true;
    try {
      let width: number, height: number;
      if (this.state.source === 'computer') {
        if (!this.video.videoWidth) return;
        [width, height] = this.drawFrame(this.video, this.video.videoWidth, this.video.videoHeight, rotation);
      } else {
        const controller = new AbortController();
        this.frameAbort = controller;
        const timeout = setTimeout(() => controller.abort(), 5000);
        let image: ImageBitmap;
        try {
          const response = await fetch(`${this.glassesBase}/frame.jpg?t=${Date.now()}`, { cache: 'no-store', signal: controller.signal });
          if (!response.ok) throw new Error(`Glasses snapshot returned ${response.status}`);
          image = await createImageBitmap(await response.blob());
        } finally { clearTimeout(timeout); if (this.frameAbort === controller) this.frameAbort = null; }
        try {
          if (generation !== this.generation) return;
          [width, height] = this.drawFrame(image, image.width, image.height, rotation);
          if (this.state.sourceError || !this.state.frameSize || this.state.frameSize[0] !== image.width || this.state.frameSize[1] !== image.height) {
            this.update({ sourceError: '', frameSize: [image.width, image.height] });
          }
        } finally { image.close(); }
      }
      const blob = await new Promise<Blob | null>(resolve => this.canvas.toBlob(resolve, 'image/jpeg', .75));
      if (!blob || generation !== this.generation || rotation !== this.state.rotation ||
          this.socket !== socket || socket.readyState !== WebSocket.OPEN) return;
      const id = ++this.frameId;
      this.pendingId = id;
      this.pendingRotation = rotation;
      socket.send(JSON.stringify({ type: 'frame', id, width, height }));
      socket.send(blob);
      this.pendingTimer = setTimeout(() => { if (this.pendingId === id) socket.close(); }, 12000);
    } catch {
      if (generation === this.generation && this.state.source === 'glasses') {
        this.nextGlassesAttempt = Date.now() + 2000;
        this.update({ sourceError: 'Cannot read the glasses camera. Check its address and tap_stream.py.',
          detections: [], updatedAt: null, processingMs: null });
      }
    } finally { if (generation === this.generation) this.capturing = false; }
  }
  private drawFrame(source: CanvasImageSource, sourceWidth: number, sourceHeight: number, rotation: CameraRotation): [number, number] {
    const [rotatedWidth, rotatedHeight] = rotatedDimensions(sourceWidth, sourceHeight, rotation);
    const scale = Math.min(1, 640 / Math.max(rotatedWidth, rotatedHeight));
    const width = Math.max(1, Math.round(rotatedWidth * scale));
    const height = Math.max(1, Math.round(rotatedHeight * scale));
    this.canvas.width = width; this.canvas.height = height;
    drawRotatedFrame(this.canvas.getContext('2d')!, source, sourceWidth, sourceHeight,
      rotation, width / 2, height / 2, scale);
    return [width, height];
  }
}

function isDetection(value: unknown): value is LiveDetection {
  if (!value || typeof value !== 'object') return false;
  const item = value as LiveDetection;
  return typeof item.label === 'string' && Number.isFinite(item.confidence) && item.confidence >= 0 && item.confidence <= 1 && Array.isArray(item.box) && item.box.length === 4 && item.box.every(n => Number.isFinite(n) && n >= 0 && n <= 1) && item.box[2] > item.box[0] && item.box[3] > item.box[1];
}
