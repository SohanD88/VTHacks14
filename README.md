# Spatial Intelligence · VTHacks14

A local video-to-3D reconstruction and editing application. Upload a room video or record a webcam, run a background reconstruction, inspect the observed room and camera path, edit furniture, and export/reload the complete scene.

**The production reconstruction path reads actual video frames. The active backend/frontend path uses no office/corridor fixtures or filename-based geometry.** Results are deliberately marked **degraded / partial**: monocular depth is approximate, hidden surfaces are unknown, and semantic predictions are not ground truth. Fitted furniture is explicitly distinguished from observed geometry.

## Start the application

Requirements: Python 3.11+, Node 22.12+, `uv`, and a modern WebGL browser. macOS Apple Silicon was tested; Linux CPU/CUDA installations should work with compatible PyTorch/OpenCV wheels but were not tested. Native Windows is not supported by the current Unix memory-measurement dependency; use WSL2.

From this repository:

```bash
cd backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8014
```

In a second terminal:

```bash
cd frontend
npm ci
API_PROXY_TARGET=http://127.0.0.1:8014 npm run dev -- --port 5174
```

Open **http://127.0.0.1:5174**. Health: **http://127.0.0.1:8014/api/health**. API documentation: **http://127.0.0.1:8014/docs**. These validation ports avoid interfering with existing servers on 8000/5173. Vite's ordinary defaults remain 5173 → 8000; change the proxy and API port together if using those ports.

Run one API process, without `--workers` or auto-reload during reconstruction. This is a local demo, with no authentication or distributed job scheduler. Keep it bound to localhost.

## Models and hardware

Inference runs locally. The first reconstruction downloads official model weights into `.model-cache/`; internet is needed for that initial download. Videos and frames are not sent to a model service.

- [Depth Anything V2 Metric Indoor Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf): approximate indoor metric depth.
- [SegFormer B2 / ADE20K](https://huggingface.co/nvidia/segformer-b2-finetuned-ade-512-512): broad room-surface and object segmentation.
- RF-DETR Nano: instance boxes for chairs, sofas and tables, and the existing optional live 2D camera detector. Its checkpoint is approximately 349 MB.
- OpenCV: FFmpeg video decoding, SIFT, RANSAC/PnP, connected regions and frame quality.
- NumPy/SciPy: geometry, registration mathematics, mesh fusion and component separation.

CUDA is selected when available, then Apple MPS, then CPU. The dashboard reports the actual device. No GPU is required; CPU performance will be slower and has not been benchmarked here. The validated machine has 12 CPU cores, 16 GB RAM and Apple MPS. Keep several GB of free memory and disk space. Model download/loading is included in the first run's duration; warmed runs are faster. Model load/resource failures become failed jobs with a stage and retry guidance, never mock scenes.

The latest balanced runs processed the six-second lounge video in **35.1 s** and the 13.8-second meeting-room video in **19.7 s**, with **60 FPS** sampled in the modeler. These are local MPS measurements, not CPU guarantees; model loading and browser/ML contention affect timings. See [the real-video review](docs/real-video-review.md) for measurements and unresolved geometric acceptance items.

## Upload and capture

1. Choose a video, scan name and quality. The browser shows the selected input preview; active-scan metadata is separately labeled.
2. Press **Reconstruct video**. Measured decoded/selected frames, poses, stages, progress and elapsed processing time update through polling.
3. Use **Cancel processing** to request cooperative cancellation. Cancellation is checked between decoder/model/geometry work units; it cannot interrupt a single GPU inference or download immediately.
4. A finished partial reconstruction shows warnings, semantic elements, opening candidates, artifact size and the real preview.
5. Choose **Recent scans** to reload persisted results. Their source video and diagnostics remain available locally. **Delete saved scan** removes that scan and its artifacts after confirmation.

Supported extensions: MP4, MOV, WebM, AVI and MKV, subject to the installed FFmpeg decoder. Phone rotation metadata is applied before inference. Both supplied HEVC MOV files decoded successfully. H.264 MP4 is the most portable browser preview format; a browser may be unable to preview a codec the backend can decode.

Default limits: 250 MB/upload, 0.5–180 seconds, no more than 4096×4096 decoded pixels, 20 saved scans, three active/queued jobs and a 2 GB managed-storage budget with conservative per-job reservations. Empty, unreadable, oversized, short and unsupported inputs are rejected. Server-generated UUID folders and safe filenames are used throughout.

For webcam capture, open **Live camera capture**, press **Start camera**, grant camera permission, then **Start recording** and **Stop recording**. Review the recording before submitting it. Camera access requires localhost or HTTPS and `getUserMedia`; recording requires `MediaRecorder`. Stopping the camera releases its tracks. Live 2D detections are explicitly labeled separately and never counted as reconstructed 3D objects.

## Quality modes

| Mode | Selected-frame budget | Maximum image side | Geometry sample stride |
|---|---:|---:|---:|
| Quick preview | 12 | 384 px | 5 px |
| Balanced | 28–48, adapted to clip duration | 518 px | 5 px |
| High quality | 56 | 644 px | 6 px |

Selection also depends on sharpness, brightness, duplicates and temporal coverage. Rejection reports distinguish intentional sampling/keyframe-budget exclusions from blur/exposure failures. More frames can help tracking but cannot recover unseen geometry or guarantee a better reconstruction from a fast pan.

## Editing

**Enter Sandbox** opens the full workspace. Drag to orbit, right-drag to pan, and scroll or use the visible zoom/reset-view controls. Click geometry to select it, or use the accessible **Scene element** selector. Hover and selection have different outlines. Metadata remains accessible outside WebGL.

- **Move** and **Rotate** attach Three.js transform controls. Numeric position/rotation fields, **Move left/right**, and **Rotate 15°** provide visible alternatives.
- **Delete object**, **Undo**, **Redo**, and **Reset scene** persist real scene state. Reset uses the immutable original reconstruction. The undo/redo history is session-local and bounded to 30 edits; saved edits survive application/backend reloads.
- Structural elements are locked until **Enable structural editing** is checked. Structural deletion requires confirmation. Openings are amber portal frames, not solid obstructions, and their exit function remains unverified.
- Toggle labels, structure, entrances/exits, uncertain geometry, camera path, cutaway walls/ceiling, **Observed surfaces**, and **Moving candidates**. Moving candidates are initially hidden and retain a single observed snapshot with a transient flag.
- Cutaway clips upper walls, ceilings and unedited surfaces linked to those walls at 1.3 estimated meters. Turn it off to inspect full observed boundaries, windows and artwork. Openings remain highlighted. User-moved artwork is not hidden by its old wall relationship. Thin observed surfaces render from both sides; this adds no wall thickness or geometry. Clicks ignore clipped faces, and view toggles do not change saved/exported scene data.
- Fitted furniture uses recognizable composite shapes: sofas have seats, backs, arms and feet; chairs have seats, backs and legs; tables have an oval/round top and pedestal. Sizes and placement come from observed depth with documented dimensional priors and an estimated floor. The source surface is retained for comparison. These are labeled `primitive_fitted`, not measured meshes.
- Empty space means unobserved geometry, not a confirmed free route. Whole-room coverage is **unknown**; no fabricated percentage is displayed.

Saving edits sends a small revision-checked transform transaction. On a failure, the previous persisted scene is restored and an error is shown. A revision conflict requires reselecting the saved scan before retrying. Ground-supported furniture cannot be moved below its estimated support plane through the normal UI.

## Room scale in the Sandbox

Open **Enter Sandbox → Room scale → Pick doorway width**. Click the two inner sides of one visible doorway at the same height; orbit/zoom between clicks if necessary. An amber line marks the selected span. Enter the reference width in feet, leave **Assumed doorway width** selected, and press **Apply room scale**. The default is **3.5 ft (1.0668 m)**, per the prototype's assumption. Select **I measured this width** only if you actually measured it. If no doorway is visible, retain the depth estimate; the application does not invent a reference or assume that every opening has the same width.

Calibration uniformly scales every object's position and scale, including retained observed surfaces, and the camera path. Geometry, rotations, IDs, source frames, semantic labels and relationships remain intact. It does not fix depth distortion or establish doorway traversability. The selected span and assumption survive save/reload and JSON export/import. **Undo/Redo** includes calibration; **Remove scale reference** restores the original scale while keeping object edits; **Reset scene** restores the complete original reconstruction. The Sandbox URL retains the scan ID so a page reload restores the saved scene.

The optional `scene.calibration` stores two reference points in **original uncalibrated world coordinates**, the reference `distance_m`, and `basis` (`assumed` or `measured`, both supplied by the user). The total factor is `distance_m / distance(reference_points)`. Current object transforms and camera coordinates already include that factor: **do not apply it again** when consuming the exported scene. Mesh vertices, `size`, and `original_transform` retain their original local values. Current dimensions are `size * scale`; world mesh points are `position + rotation(scale * vertex)`. `scale_note` labels the assumption and remaining uncertainty; units remain `estimated_meters`. Old version-2 scenes without calibration continue to load. Original PLY/diagnostic JSON remains uncalibrated; use **Export JSON** for the calibrated current scene.

The current milestone preserves the video-derived 3D rendering and its future use for navigation. Navigation annotations, free-space inference, route finding, LiDAR capture/import and photorealistic cleanup are intentionally deferred, as agreed in the task. Empty reconstructed space is still unknown, not a verified route. Additional demo videos can be added under `TestVideosOfRooms/navigation-demo/` without removing the original two inputs.

## Scene format, persistence and API

The version-2 JSON scene uses Y-up coordinates and `estimated_meters`. Each element contains a stable ID, class/name, confidence, position/rotation/scale, dimensions, colored triangle geometry, optional observed geometry, source-frame IDs, supporting-surface/relationship references, structural/movable/editable flags, opening flag, provenance, original transform and edited/deleted state. Unknown candidates retain observed surfaces instead of receiving confident labels.

**Export JSON** contains both the current edited scan and original scene, including geometry and provenance. **Import JSON** validates the version, finite/bounded geometry, triangle indices, original/current identity and immutable provenance, then saves a new scan. Source-frame references survive import; source images/video stay with the original scan and are not embedded in the export. The UI explicitly explains this for imports.

Key endpoints:

- `POST /api/scans`: multipart `file`, `name`, `mode`, `source`; returns 202.
- `GET /api/scans`: recent jobs without mesh payloads.
- `GET /api/scans/{id}/status`: lightweight measured state.
- `GET /api/scans/{id}`: current edited scan.
- `POST /api/scans/{id}/cancel`; `DELETE /api/scans/{id}`.
- `GET /api/scans/{id}/original`; `POST /api/scans/{id}/reset`.
- `POST /api/scans/{id}/calibration`: revision plus reference points, distance and basis (or null to remove).
- `PATCH /api/scans/{id}/transforms`: revision plus changed transforms/deletions, optionally a calibration for history restoration.
- `PUT /api/scans/{id}/scene`: validated full-scene transform compatibility endpoint.
- `GET /api/scans/{id}/export`; `POST /api/scans/import`.
- `GET /api/scans/{id}/artifacts/{allowed-name}`: source media, frames, overlays, depth/masks, trajectory, quality report, original mesh JSON and PLY.

The PLY and `scene.json` diagnostic artifacts describe the original generated reconstruction. Use **Export JSON** for edits. Confidence values are model outputs/observation aggregates, not calibrated probabilities of physical correctness.

Jobs run on one background worker, keeping model inference off HTTP request handling. Metadata stays in memory; saved meshes are loaded from disk on demand. Atomic JSON replacement persists jobs and edits. On restart, completed results recover, while interrupted jobs become failed with retry instructions. Model weights survive restarts. Temporary upload files are removed on failure/cancellation; successful source media is renamed to a controlled artifact. Deleting a scan removes its entire managed directory. There is no silent eviction of user edits.

## Architecture

```text
video.py           validation, orientation-aware decoding, quality, keyframes, discovery
vision.py          metric depth + ADE20K segmentation + RF-DETR instance evidence
geometry.py        SIFT/PnP RGB-D tracking, scale alignment, semantic surface fusion
relocalization.py  Multi-reference recovery of missed camera poses
registration.py    bounded joint pose/depth refinement with measured acceptance gates
tracking.py        one-to-one assignment and reciprocal-projection track consolidation
motion.py          repeated cross-frame motion evidence with background consistency gates
surfaces.py        observed wall planes, supported corner seams and boundary insets
sampling.py        bounded adaptive sampling of small observed semantic surfaces
fixtures.py        ceiling-supported light fits with multi-view silhouette checks
openings.py        observed jamb/lintel portal fits with repeated RGB/depth support
assets.py          explicitly labeled evidence-scaled furniture fits
reconstruction.py  stage orchestration, warnings, measurements, artifacts
store.py           persistent jobs, worker, cancellation, quotas, atomic writes
routes/scans.py    upload/status/edit/export/import/artifact API
SceneViewer.tsx    observed/fitted geometry, cutaway, raycasting, transform controls
Modeler.tsx        protected editing, metadata, undo/redo, persistence, export/import
Dashboard.tsx     inputs, recording, measured job state, active-scene statistics
```

The pipeline uses learned metric depth rather than unscaled two-view triangulation because these clips include low-texture walls and limited parallax. SIFT correspondences plus depth support robust camera PnP, and depth scale is aligned across accepted observations. Missed poses are retried against localized views using reciprocal feature matches and agreement between at least two reference estimates. Up to three recovery passes precede joint refinement; recovery provenance is saved in `camera-poses.json`. Views still failing these checks are excluded from fusion. Person/animal semantic regions are excluded from permanent geometry. Matched image features can identify other moving candidates when they repeatedly disagree with camera motion while background features remain consistent. These tracks retain one observed snapshot in a separate transient layer; sparse or ambiguous motion evidence is explicitly unverified. Disconnected semantic components retain only their contributing frames and observation scores, so isolated fragments cannot borrow confidence from another surface. Fitted semantic tables also estimate width from their own contributing points in each camera view, excluding neighboring components. Small semantic surfaces missed by the coarse grid receive bounded local pixel sampling, retain source evidence, and remain uncertain without repeated support. Nearby observations are voxel-fused, depth discontinuities are not bridged with triangles, and an observed floor plane defines the up axis; observations within 25 cm of that plane are flattened without filling missing floor or changing other elevations. Object instances are associated across each frame with a one-to-one assignment using 3D distance and reciprocal mask projection across recent views. Strong image support admits bounded depth drift; separate detections visible together retain distinct identities. Disjoint tracks can merge when their observed surfaces project consistently into each other's image masks, with class, distance and appearance checks. Co-visible tracks cannot merge, including through an intermediate track. Repeated confident semantic sofa, table and chair regions can also receive fits when instance boxes miss the visible surfaces. Fitted furniture avoids treating a noisy or partial surface as a finished cuboid.

Accepted poses and per-view depth scales are jointly refined using feature matches in overlapping and return views. A bounded robust fit is applied only when its 3D consistency improves without materially worsening reprojection; otherwise original poses remain. Vertical wall planes are fitted to observed points and meshed only in supported cells, preserving holes and incomplete boundaries. For meshed observations, robust local surface normals must agree with each proposed plane; a line of unrelated surfaces cannot support a cross-cutting wall merely through positional proximity. Degenerate or ambiguous normals remain unsupported, and unfitted observations are retained in the uncertain layer. Plane orientation support is recorded in `structure-fit.json`. Nearby wall edges share corner vertices only at mutually observed heights; unsupported gaps remain open. Corner adjustments and adjacency are recorded in the structural diagnostics. Nearby wall-associated surfaces are aligned while retaining their raw evidence. Repeatedly observed lights near a supported ceiling can receive a plane-constrained fit only with multi-view silhouette agreement. Their source triangles and raw geometry remain available, and installed light candidates receive structural editing protection. Disjoint light tracks merge only with reciprocal mask agreement; nearby position alone is insufficient. `fixture-fit.json` records all accepted fits and merges. Doorway candidates can receive a stored open-frame mesh when visible jambs, a lintel, a depth gap and interior floor agree across at least three localized views. Their lower edge is inferred from the observed floor, and the raw door surface is retained. `opening-fit.json` records the source views and checks. The browser renders this stored geometry, preserving the outline through export/import. **Observed surfaces** switches between raw and fitted geometry.

This is not full landmark bundle adjustment, globally optimized SLAM, calibrated photogrammetry, dense multi-view stereo or a watertight building model. See the real-video review for observed fidelity and remaining limitations.

## Verify

```bash
# backend/
uv run pytest -q
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts

# frontend/
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
# Or use an installed Google Chrome:
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

Fast API tests use tiny decoded videos and a controlled provider. They test upload validation, progress/state, cancellation, safe failures, quotas, contracts, artifacts, editing, structural protection, import/reset and restart recovery. Browser contract tests use a clearly synthetic editor fixture; they do not claim reconstruction quality. Live-camera tests use a virtual webcam and controlled detection responses. A separate test records a real browser-generated WebM blob. The browser suite also checks hover/click selection, transform editing/history, responsive layout and WebGL failure behavior.

The browser tests use persistent API storage by default. Leave at least two free scan slots for editor/export-import checks. If the evaluation server is being used interactively, run editor tests against a separate API and frontend instead of deleting existing scans:

```bash
# Separate terminal, backend/:
SPATIAL_DATA_DIR=/tmp/vthacks14-editor-verification .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8015
# Separate terminal, frontend/:
API_PROXY_TARGET=http://127.0.0.1:8015 npm run dev -- --port 5175
# frontend/:
PLAYWRIGHT_CHANNEL=chrome TEST_API_URL=http://127.0.0.1:8015/api TEST_BASE_URL=http://127.0.0.1:5175 npm run test:e2e -- tests/scan.spec.ts --workers=1
```

Real-video integration (start the servers first):

```bash
# repository root; inspect and recursively discover the actual inputs
backend/.venv/bin/python backend/scripts/inspect_videos.py --root .

# Submit both discovered videos through the API
backend/.venv/bin/python backend/scripts/evaluate_videos.py \
  --root . --mode balanced --api http://127.0.0.1:8014/api

cd frontend
PLAYWRIGHT_CHANNEL=chrome RUN_REAL_VIDEO=1 npm run test:e2e -- --workers=1

# Optional high-quality comparison (run evaluator with --mode high first):
PLAYWRIGHT_CHANNEL=chrome RUN_REAL_VIDEO=1 REAL_VIDEO_MODE=high npm run test:e2e -- tests/real-video.spec.ts --workers=1
```

For the Sandbox scale comparison, pass `--output test-results/real-video/scale-calibration` to the evaluator and set `REAL_VIDEO_RESULTS_DIR=../test-results/real-video/scale-calibration` for the browser tests. Set `TEST_API_URL=http://127.0.0.1:8016/api` and `TEST_BASE_URL=http://127.0.0.1:5176` for its isolated API/frontend. The original mask-association comparison remains in its own folder; the main manifest retains the earlier opening iteration. Use a matching fresh API build when trying the new calibration endpoint.

The evaluator ignores dependency/cache/artifact directories and recognizes video extensions independently of automated test source files. The supplied videos currently reside in `TestVideosOfRooms/`. Browser real-video tests read the saved evaluator outputs, load each actual scan in Three.js, edit it, export/import it and reset it. Expensive inference is not repeated by every unit/browser test.

Artifacts:

- `test-results/video-inspection/`: initial metadata/contact sheets.
- `test-results/real-video/`: actual API results and iteration summaries.
- `.spatial-data/<scan-id>/`: source video, accepted JPEGs, quality report, semantic/detection overlays, depth arrays/maps, original/refined camera-pose matrices, registration acceptance/residuals (`registration.json`), plane-fit support (`structure-fit.json`), ceiling-light support (`fixture-fit.json`), opening-outline evidence (`opening-fit.json`), reciprocal track merges (`instance-tracks.json`), motion evidence (`motion-report.json`), refined depth arrays, masks, PLY, original/edited JSON and metrics.
- `frontend/test-results/`: dashboard/modeler/mobile screenshots and failure traces.
- `docs/real-video-review.md`: measured results and visual review.

Generated media, weights and result files are ignored by Git. Keep them locally for review, or copy them explicitly when handing the project to another machine.

## Configuration and troubleshooting

Use `backend/.env` / `frontend/.env` based on the examples. Available backend settings include `SPATIAL_MODEL_CACHE`, `SPATIAL_DATA_DIR`, `SPATIAL_MAX_UPLOAD_BYTES`, `SPATIAL_MAX_STORAGE_BYTES`, `SPATIAL_MAX_STORED_SCANS`, `SPATIAL_DETECTION_CONFIDENCE`, `SPATIAL_CORS_ORIGINS` and `SPATIAL_LOG_LEVEL`.

- **API offline:** use matching API/proxy ports and restart Vite after configuration changes.
- **Model weights unavailable:** allow the official initial downloads, check free disk space, and retry. No API key is required.
- **Unsupported codec / browser preview fails:** re-export H.264 MP4; backend support and browser playback support differ.
- **Lost tracking / low-detail output:** record slowly with textured overlap, sideways translation, steady lighting and return views; try balanced/high quality. Do not only rotate in place.
- **No entrance or furniture:** the UI reports this explicitly. It does not imply the room lacks those elements.
- **Resource failure:** choose quick mode, shorten the clip and close other GPU applications. CPU is supported but slower.
- **Storage full:** delete obsolete saved scans through the UI; user edits are not silently discarded.
- **WebGL unavailable:** enable browser hardware acceleration/WebGL. HTML metadata and JSON export remain available.
- **Camera permission failure:** grant permission in browser site settings and use localhost/HTTPS.
- **Uncertain geometry:** toggle low-confidence surfaces and observed surfaces, inspect source frames, and treat positions/scale as approximate.

## Deployment boundary

The checked-in `.openai/hosting.json` and root `dist/` belong to the earlier static site. The validated application is `frontend/` plus `backend/`; root `dist/` is not its production build. Static/Cloudflare Worker hosting alone cannot execute this CPython/PyTorch/OpenCV worker or provide its local model cache and durable filesystem. A hosted deployment requires a separately provisioned Python compute service, persistent storage, authentication and a configured API origin. No incomplete static-only deployment was published as a working reconstruction service.

## Fidelity limits

The videos do not provide calibrated intrinsics, measured distances, depth sensors or a complete room survey. Absolute scale, true whole-room coverage, occluded backs/legs, exact wall thickness and whether a visible opening is an exit cannot be established from these inputs. Transparent windows and reflective surfaces distort learned depth. The latest balanced evaluation localizes 28/28 lounge views and 37/41 meeting-room views; four low-texture meeting-room views remain excluded. More views improve observed coverage but do not verify the unique chair inventory or fixture labels. Fitted seating uses the nearest surviving static table as an orientation prior; this is a layout heuristic, not an observed facing-direction measurement. Remaining fragments, duplicate candidates, imperfect orientations and erroneous labels are possible. Opening fits require repeated visible jamb/lintel and floor evidence; they do not recover every passage or establish that a candidate is an exit. The lower opening edge is inferred from the estimated floor, and its thin visual frame is not measured trim. Recovered ceiling-light patches can be fitted to an observed ceiling plane when multiple views support the fit. Their raw depth surfaces remain available, but ceiling attachment, dimensions and unique fixture count are still estimates. Suspected duplicates without sufficient reciprocal evidence stay separate. One smaller lounge sofa candidate remains uncertain after correcting its component-specific evidence. The offline CLIP fixture experiment was not adopted; CLIP weights are not an application requirement. Moving candidates require repeated feature evidence and a stable camera/background model. Sparse texture, occlusion, rapid track breaks and motion consistent with epipolar geometry can evade the check. Human/animal masking and sparse motion checks do not provide complete dynamic-object segmentation. The application therefore keeps a partial/degraded status, source evidence, and raw-versus-fitted provenance visible instead of claiming a fully accurate reconstruction.

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

The glasses script requires local camera access and its own process. The live preview provides 2D detection. To reconstruct glasses footage, record it with the glasses controls and select the saved video in the dashboard’s Video file input. Browser Start recording captures the Computer webcam source.
