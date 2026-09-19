# Spatial Intelligence · VTHacks14

A working first vertical slice of the Spatial Intelligence Platform. The frontend carries over the existing Sites design: black/white/cyan dashboard, camera panel, interactive 3D preview, detections, spatial statistics, and a transition into the full modeling workspace with render controls and the agent dock.

**Run demo scan → real HTTP request → FastAPI → reconstruction service → scene JSON → React state → Three.js model and dashboard.**

## Run locally

Prerequisites: Node.js **22.12+** (Node 22 LTS recommended), Python **3.11+**, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Both dependency lockfiles are included. No API keys are required.

Terminal 1 — backend:

```bash
cd "/Users/ashmitrama/Documents/CS Projects/VTHacks14/VTHacks14/backend"
cp .env.example .env
uv sync --locked
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```bash
cd "/Users/ashmitrama/Documents/CS Projects/VTHacks14/VTHacks14/frontend"
cp .env.example .env
npm ci
npm run dev
```

On another machine, substitute your clone's path. Open **http://127.0.0.1:5173**. API health is at **http://127.0.0.1:8000/api/health** and interactive API docs at **http://127.0.0.1:8000/docs**.

Choose **Operations room** or **East corridor**, enter a scan name, and press **Run demo scan**. The API produces a unique scan ID with scene geometry and statistics. Open the 3D environment, orbit/zoom/reset the scene, and use **Export JSON** to download the actual response. Switch sample capture and scan again to see a different model and counts.

## Structure

```text
frontend/
  src/App.tsx                   Scan state, request lifecycle, navigation
  src/types.ts                  Typed API and scene contracts
  src/services/api.ts           Shared API client, timeouts, structured errors
  src/components/Dashboard.tsx  Scan form, camera, detections, statistics
  src/components/SceneViewer.tsx Three.js rendering, orbit/zoom, resource cleanup
  src/components/Modeler.tsx    Full workspace and JSON export
  src/components/CameraFeed.tsx Live video and responsive detection overlays
  src/styles.css               Original Sites styles plus integration states
  tests/scan.spec.ts            Browser integration tests
  vite.config.ts               Development/preview API proxy
backend/
  app/main.py                  App factory, health, CORS, logging, error handlers
  app/config.py                Environment configuration
  app/schemas.py               Validated requests and responses
  app/routes/scans.py           Create/retrieve scan routes
  app/services/reconstruction.py Provider contract and mock implementation
  app/services/store.py         Bounded process-local scan store
  tests/test_api.py             API, validation, error, CORS, and storage tests
```

## API and data flow

- `GET /api/health` returns service availability and `processing_mode: "mock"`.
- `POST /api/scans` accepts `{ "name": "Level 01", "preset": "office", "source": "demo" }` and returns **201** with a completed scan.
- `GET /api/scans/{id}` retrieves a scan from the current API process, or returns **404** when absent/expired.
- Validation errors use **422**. All API errors use `{ "error": { "code", "message", "request_id", "fields" } }`.

The POST route validates input, calls the injected `ReconstructionService`, stores the response, and returns room geometry, objects, camera path, detections, and statistics. Object positions represent their **centers in meters, with Y up**. React stores the response centrally; both views consume the same scene. No result fixtures are embedded in the frontend.

Loading disables duplicate submissions. Errors show a retry action and retain any previous successful scene. Empty and WebGL-unavailable states explain what is missing. Navigation supports browser back, `#modeler`, and Escape. Export downloads the complete scene JSON; it does not claim to export a mesh.

## Configuration

`frontend/.env.example`:

- `VITE_API_BASE_URL=/api`: browser API prefix. This is public configuration.
- `API_PROXY_TARGET=http://127.0.0.1:8000`: server-side target used by Vite development and preview.

`backend/.env.example`:

- `SPATIAL_CORS_ORIGINS`: JSON array of allowed frontend origins.
- `SPATIAL_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, or `ERROR`.
- `SPATIAL_MAX_STORED_SCANS=100`: maximum scans retained in the API process.

Defaults work without creating `.env` files. For another frontend port/origin, update the proxy/CORS configuration together. Restart Vite after changing its environment. `VITE_*` values are embedded into the browser bundle; never put secrets there. `.env`, generated files, environments, and dependencies are ignored.

## Verify

```bash
# In backend/
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests

# In frontend/
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests start both servers if needed. They exercise the actual API and verify its returned scan ID, counts, geometry, navigation, and downloaded JSON. Separate tests inject a network failure to verify loading/retry/retained results, and check the mobile layout and empty deep link. Browser failures retain traces and screenshots in `frontend/test-results/`. If Google Chrome is installed, `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` avoids the Chromium download.

For a production-build smoke check, run `npm run preview` with the backend running. A deployed static build needs a reverse proxy for `/api` or an absolute `VITE_API_BASE_URL` set at build time, plus the corresponding backend CORS origin. This iteration does not deploy the backend or change the published Sites app.

## What is mocked and what comes next

**Mocked:** demo scan geometry, scan frame counts, demo-scene detection metadata, and coverage. Live camera detections are real RF-DETR inference and are displayed separately from the demo scan. The two deterministic sample scenes live only in `MockReconstructionService`. Browser camera access and 2D object detection are implemented. Media upload and actual 3D reconstruction are not yet implemented. Editing and agent tools are visibly disabled as planned features.

**Real:** frontend/API transport, validation, service invocation, scan IDs/timestamps, returned scene data, Three.js rendering, orbit/zoom controls, error handling, and JSON export.

Storage is in memory, bounded, and single-process. API restarts clear stored scans. Browser reloads clear the selected scene; there is no persisted account or project history. Run one API worker for this prototype. Longer reconstruction jobs will need a job/status interface instead of holding a synchronous request open.

The next layer is recorded capture/upload ingestion and camera pose estimation, followed by an asynchronous reconstruction provider. Keep the existing scene contract and replace the mock provider with real image processing; introduce persistent scan/job storage when that pipeline needs it. Editable objects and agent actions can then operate on the same scene graph.

## Implementation references

- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) and [error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Vite environment configuration](https://vite.dev/guide/env-and-mode) and [development proxy](https://vite.dev/config/server-options)
- [Three.js OrbitControls](https://threejs.org/docs/pages/OrbitControls.html)


## Live camera integration from SDObjectDetection

Adapted from `origin/SDObjectDetection` at `e646087`. The source branch uses **RF-DETR Nano**, **PyTorch 2.8 / torchvision 0.23**, and **Pillow**, plus FastAPI WebSockets and browser `getUserMedia`. It contains no direct OpenCV (`cv2`) processing loop or Google vision model. This integration preserves its detector and protocol behavior in the existing React dashboard instead of importing the standalone HTML app.

Start both servers using the commands above, open the dashboard, click **Start camera**, and allow browser camera access. Hold up a supported object such as a cup, bottle, book, laptop, chair, or person. Select another camera when multiple devices are available. The live video, labels, confidence scores, and normalized bounding boxes also appear in the modeling room's camera tile. Navigation reuses the same stream and inference connection. **Stop camera** releases the media tracks and connection; **Retry detection** retries model-load failures.

Dependencies install with `uv sync --locked`. The initial connection downloads the approximately 349 MB RF-DETR Nano checkpoint, then warms the model before accepting frames. The ignored cache defaults to the repository’s `.model-cache` (override with `SPATIAL_MODEL_CACHE`, or RF-DETR's `RF_HOME`). `SPATIAL_DETECTION_CONFIDENCE=0.5` controls filtering; the source branch's `DETECTION_CONFIDENCE` environment variable is also accepted. Model inference speed depends on hardware.

`GET /api/health` retains the scan API fields and adds `camera: { engine: "rf-detr-nano", model: "unloaded|loading|ready|error" }`. The existing top-level `processing_mode: "mock"` describes **3D reconstruction**, not camera detection.

### Camera path

`getUserMedia → sampled JPEG → /api/camera/detect WebSocket → validated Pillow image → RF-DETR Nano → normalized detections → React state → video overlays and detection list`

- Video remains local and smooth. At most about 3 sampled frames/second are sent, resized to at most 640 pixels wide at JPEG quality 0.75.
- Only one frame is in flight per session. The next waits for a matching response ID; a 12-second stalled frame reconnects. Model startup has a separate three-minute timeout.
- Server sends loading/ready status. Client sends a text JSON header `{ type: "frame", id, width, height }`, then a binary JPEG. Results use `{ type: "detections", id, width, height, detections, processing_ms }`.
- Each detection contains `label`, `confidence`, and `box: [left, top, right, bottom]` normalized to 0–1. The overlay accounts for letterboxing and resizes with the panel.
- Server limits JPEGs to 4 MB and 4096 pixels per side. Frames are decoded/inferred in a worker thread and are not saved. A model lock serializes inference.
- The detections panel reports objects in the **latest frame**, not persistent tracked identities. The branch does not provide identity tracking, arbitrary-object recognition, depth, or 3D reconstruction.
- Vite proxies `/api` including WebSockets. An absolute `VITE_API_BASE_URL` also determines the detection WebSocket host/path; HTTPS uses WSS. Browser origins must be listed in `SPATIAL_CORS_ORIGINS`, including for WebSocket access.
- Camera access needs localhost or HTTPS. A webcam connected to the browser's machine works; a separate wearable sender would need its own ingest integration.

Key additions: `frontend/src/services/liveCamera.ts` owns capture, sampling, reconnect, and cleanup; `frontend/src/hooks/useLiveCamera.ts` shares session state; `backend/app/services/detection.py` owns model loading/inference; `backend/app/routes/camera.py` owns the validated socket protocol. Camera tests use a virtual browser camera and controlled detector results; backend tests cover the real socket contract with a stub model. These tests do not access a physical webcam.

Optional actual-model check (downloads weights on first use): from `backend/`, run `uv run python scripts/smoke_camera.py /path/to/image.jpg`. Omit the image path to send a blank synthetic frame through the real WebSocket and model.

## Glasses camera source

The `smayanGlasses` capture script and Arduino sketch are included in `backend/glassesFiles/`; the branch's sample recordings are excluded. The camera is a USB webcam attached to the **same computer** as the dashboard. The glasses script opens that webcam and serves video on port 8080. The browser should use the computer's built-in webcam when **Computer webcam** is selected; a camera already opened by the glasses script usually cannot be opened by the browser at the same time.

In a third terminal at the repository root, install the glasses script's separate dependencies and start it:

```bash
cd backend/glassesFiles
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tap_stream.py --camera 1 --rotate ccw
```

Use the camera index and rotation appropriate for your hardware (`--camera 0` is another common index). On Windows, activate the virtual environment and run `python tap_stream.py --camera 1 --rotate ccw`. Open `http://127.0.0.1:8080/` to check the glasses stream and recording controls. The script serves only the local computer by default. It serves real camera video immediately; tapping sensor 1 or using its test page starts and stops **recording** without interrupting live video. If a second touch sensor is attached, set `NUM_SENSORS = 2` in the Arduino sketch to enable hazard markers during a mission. Recordings are saved outside the repository by default at `~/vt26_recordings`.

In the dashboard camera panel, select **Glasses camera**. The address defaults to `http://127.0.0.1:8080` and is remembered in this browser. Click **Start camera**. The MJPEG `/stream` supplies the preview; `/frame.jpg` supplies up to about three sampled frames per second to the existing RF-DETR WebSocket. Results and overlays appear in both dashboard and modeling views. **Rotate 90°** turns the selected live preview and detector frames clockwise in quarter turns, keeping boxes aligned; its angle carries over when switching sources or views. The script's `--rotate` option rotates its own stream and saved recordings before they reach the dashboard. Switching back to **Computer webcam** stops glasses polling and starts browser capture. The glasses script continues running until stopped in its terminal. If the stream or detector disconnects, use **Retry detection** after checking the relevant process.

The glasses script requires local camera access and its own process. This integration provides live 2D detection; the demo 3D reconstruction is still separate.
