const video = document.querySelector("#video");
const overlay = document.querySelector("#overlay");
const stage = document.querySelector("#stage");
const emptyState = document.querySelector("#empty-state");
const cameraButton = document.querySelector("#toggle-camera");
const cameraSelect = document.querySelector("#camera-select");
const cameraStatus = document.querySelector("#camera-status");
const modelStatus = document.querySelector("#model-status");
const message = document.querySelector("#message");
const count = document.querySelector("#object-count");
const list = document.querySelector("#detection-list");
const updateTime = document.querySelector("#update-time");
const captureCanvas = document.createElement("canvas");
const captureContext = captureCanvas.getContext("2d");
const overlayContext = overlay.getContext("2d");

let stream = null;
let socket = null;
let sendTimer = null;
let reconnectTimer = null;
let pendingTimer = null;
let pending = false;
let pendingId = null;
let ready = false;
let frameId = 0;
let detections = [];
let active = false;
let modelFailed = false;

function setStatus(element, text, kind = "") {
  element.textContent = text;
  element.className = `status ${kind}`;
}

function setMessage(text) { message.textContent = text; }

function clearPending() {
  pending = false;
  pendingId = null;
  window.clearTimeout(pendingTimer);
  pendingTimer = null;
}

function resetResults() {
  detections = [];
  count.textContent = "00";
  list.replaceChildren();
  const hint = document.createElement("div");
  hint.className = "list-empty";
  hint.textContent = "Detected objects will appear here.";
  list.append(hint);
  updateTime.textContent = "—";
  drawOverlay();
}

function drawOverlay() {
  const rect = stage.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  overlay.width = Math.round(rect.width * scale);
  overlay.height = Math.round(rect.height * scale);
  overlayContext.scale(scale, scale);
  if (!video.videoWidth || !video.videoHeight) return;
  const fit = Math.min(rect.width / video.videoWidth, rect.height / video.videoHeight);
  const imageWidth = video.videoWidth * fit;
  const imageHeight = video.videoHeight * fit;
  const offsetX = (rect.width - imageWidth) / 2;
  const offsetY = (rect.height - imageHeight) / 2;
  overlayContext.font = "600 13px system-ui, sans-serif";
  for (const item of detections) {
    const [left, top, right, bottom] = item.box;
    const x = offsetX + left * imageWidth;
    const y = offsetY + top * imageHeight;
    const w = (right - left) * imageWidth;
    const h = (bottom - top) * imageHeight;
    overlayContext.strokeStyle = "#b9f77b";
    overlayContext.lineWidth = 2;
    overlayContext.strokeRect(x, y, w, h);
    const label = `${item.label} ${Math.round(item.confidence * 100)}%`;
    const labelWidth = overlayContext.measureText(label).width + 16;
    const labelY = Math.max(0, y - 26);
    overlayContext.fillStyle = "#b9f77b";
    overlayContext.fillRect(x, labelY, labelWidth, 25);
    overlayContext.fillStyle = "#10211c";
    overlayContext.fillText(label, x + 8, labelY + 17);
  }
}

function showDetections(items) {
  detections = items;
  count.textContent = String(items.length).padStart(2, "0");
  updateTime.textContent = new Date().toLocaleTimeString();
  list.replaceChildren();
  if (!items.length) {
    const hint = document.createElement("div");
    hint.className = "list-empty";
    hint.textContent = "No supported objects in this frame.";
    list.append(hint);
  }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "detection-item";
    const name = document.createElement("strong");
    name.textContent = item.label;
    const score = document.createElement("span");
    score.textContent = `${Math.round(item.confidence * 100)}%`;
    row.append(name, score);
    list.append(row);
  }
  drawOverlay();
}

function connect() {
  if (!active || modelFailed || socket) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws/detect`);
  socket = ws;
  ws.onopen = () => setMessage("Connected. Loading detection model…");
  ws.onmessage = (event) => {
    if (socket !== ws) return;
    let payload;
    try { payload = JSON.parse(event.data); } catch { return; }
    if (payload.type === "status") {
      ready = payload.status === "ready";
      setStatus(modelStatus, ready ? "READY" : "LOADING", ready ? "live" : "");
      setMessage(ready ? "Model ready. Hold up a common object." : "Loading pretrained model…");
    } else if (payload.type === "detections") {
      if (payload.id !== pendingId) return;
      clearPending();
      if (Array.isArray(payload.detections)) showDetections(payload.detections);
    } else if (payload.type === "error") {
      clearPending();
      setMessage(payload.message || "Detection error.");
      if (String(payload.message).startsWith("Model could not load")) {
        modelFailed = true;
        setStatus(modelStatus, "ERROR", "error");
      }
    }
  };
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    ready = false;
    clearPending();
    resetResults();
    if (active && !modelFailed) {
      setStatus(modelStatus, "RECONNECTING");
      setMessage("Detection server disconnected. Retrying…");
      reconnectTimer = window.setTimeout(connect, 2000);
    }
  };
  ws.onerror = () => { if (socket === ws) setMessage("Cannot reach detection server."); };
}

function sendFrame() {
  const ws = socket;
  if (!active || !ready || pending || ws?.readyState !== WebSocket.OPEN || !video.videoWidth) return;
  const ratio = Math.min(1, 640 / video.videoWidth);
  captureCanvas.width = Math.max(1, Math.round(video.videoWidth * ratio));
  captureCanvas.height = Math.max(1, Math.round(video.videoHeight * ratio));
  captureContext.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
  pending = true;
  const id = ++frameId;
  pendingId = id;
  captureCanvas.toBlob((blob) => {
    if (!active || socket !== ws) return;
    if (!blob || ws.readyState !== WebSocket.OPEN) {
      clearPending();
      return;
    }
    ws.send(JSON.stringify({ type: "frame", id, width: captureCanvas.width, height: captureCanvas.height }));
    ws.send(blob);
    pendingTimer = window.setTimeout(() => { if (pending) ws.close(); }, 12000);
  }, "image/jpeg", 0.75);
}

async function listCameras() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter((item) => item.kind === "videoinput");
  cameraSelect.replaceChildren();
  cameras.forEach((camera, index) => {
    const option = document.createElement("option");
    option.value = camera.deviceId;
    option.textContent = camera.label || `Camera ${index + 1}`;
    cameraSelect.append(option);
  });
  cameraSelect.hidden = cameras.length < 2;
  const trackId = stream?.getVideoTracks()[0]?.getSettings().deviceId;
  if (trackId) cameraSelect.value = trackId;
}

async function startCamera(deviceId) {
  cameraButton.disabled = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires localhost or HTTPS.");
    setMessage("Requesting camera permission…");
    const next = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
    stream?.getTracks().forEach((track) => track.stop());
    stream = next;
    video.srcObject = stream;
    await video.play();
    resetResults();
    active = true;
    modelFailed = false;
    emptyState.hidden = true;
    cameraButton.innerHTML = "Stop camera <span>×</span>";
    setStatus(cameraStatus, "LIVE", "live");
    setMessage("Camera active. Connecting to detection server…");
    try { await listCameras(); } catch { cameraSelect.hidden = true; }
    drawOverlay();
    connect();
    if (!sendTimer) sendTimer = window.setInterval(sendFrame, 333);
  } catch (error) {
    setStatus(cameraStatus, "ERROR", "error");
    setMessage(`Camera unavailable: ${error.message}`);
  } finally {
    cameraButton.disabled = false;
  }
}

function stopCamera() {
  active = false;
  ready = false;
  window.clearInterval(sendTimer);
  window.clearTimeout(reconnectTimer);
  sendTimer = null;
  reconnectTimer = null;
  clearPending();
  socket?.close();
  socket = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
  emptyState.hidden = false;
  cameraButton.innerHTML = "Start camera <span>↗</span>";
  setStatus(cameraStatus, "OFFLINE");
  setStatus(modelStatus, "STANDBY");
  setMessage("Ready to connect.");
  resetResults();
}

cameraButton.addEventListener("click", () => active ? stopCamera() : startCamera());
cameraSelect.addEventListener("change", () => startCamera(cameraSelect.value));
video.addEventListener("loadedmetadata", drawOverlay);
new ResizeObserver(drawOverlay).observe(stage);
window.addEventListener("beforeunload", stopCamera);
