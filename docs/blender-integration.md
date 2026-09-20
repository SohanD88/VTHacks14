# Blender → Sandbox integration

The app now has a Blender provider alongside the original depth reconstruction provider. Choose **Blender · structured room model** (the dashboard default), then upload a `.blend`, `.glb`, room-plan JSON, or video. Completed jobs open in the existing Sandbox.

## What is implemented

- The official Blender MCP stdio server executes the checked-in exporter/builder through `execute_blender_code_for_cli`. Each job gets an isolated seed file and background Blender process. It does not change the user's open Blender scene or original file.
- The headless transport runs the same worker directly in Blender. Both paths produce `model.blend`, a self-contained `model.glb`, semantic triangle meshes, object IDs, transforms, and cutaway metadata.
- The Sandbox loads GLB materials/textures and uses existing selection, transforms, undo/redo, structural protection, scale calibration, persistence, and JSON export/import. The embedded asset makes the application JSON export portable. Original geometry and asset data remain immutable; edits change object transforms/deletion state.
- Hidden source geometry is retained in the complete model. Cutaway mode hides objects marked hidden in the source and ceilings, keeping the other walls full height. For the procedural builder, the front wall and front doorway are hidden in cutaway. Toggle **Cutaway walls / ceiling** off to see the full shell.
- Procedural base-color shaders are baked into textures. Complex Blender shading does not transfer perfectly to glTF; browser lighting differs from a Cycles render. Static evaluated meshes are supported, not animation or rigs.
- Door geometry and semantic labels are available for later agent work. Traversability, connected floors, exit roles, navigation graphs and route planning are not implemented by this change.

## Gemini video generation

The local backend now uses **Gemini 3.6 Flash** and **google-genai 2.24.0**, matching the
successful independent café/lobby experiments. It selects up to eight sharp, temporally
distributed video frames, re-decodes them at up to 1280 pixels, and submits them with the
experiment's function-calling approach. Gemini authors detailed Blender Python, including
visible furnishings, materials, shelving and small props rather than a fixed room template.
No clip-specific furniture list or filename-based scene is injected into the prompt.

The checked-in worker saves and exports the generated scene through the official MCP CLI
tool, then loads the result into the Sandbox. The SDK makes up to three attempts for transient service errors. One automatic scene-code repair attempt is allowed for
script validation or Blender compatibility failures. The worker preserves generation
metadata, assumptions and frame references. Failed jobs report an error without replacing
the result with a canned room.

The model is still an **image-guided approximation**. Recognizable furnishings and visual
similarity do not establish measured dimensions, complete hidden geometry, or safe exits.
The prompt assumes a 1.0668 m / 3.5 ft single door width when no measurement is available.
Navigation and multi-floor connectivity are later work.

## Configure and run

The ignored local `backend/.env` selects the existing Blender installation, official MCP
server, Gemini model, and the experiment's Keychain service. Run the API from `backend/`
so it loads that file. Restart after changing settings.

```dotenv
SPATIAL_BLENDER_PROVIDER=gemini
SPATIAL_BLENDER_PLANNER_MODEL=gemini-3.6-flash
SPATIAL_GEMINI_KEYCHAIN_SERVICE=vt-hacks-gemini-api
SPATIAL_BLENDER_TRANSPORT=mcp
SPATIAL_BLENDER_BINARY=/Applications/Blender.app/Contents/MacOS/Blender
SPATIAL_BLENDER_MCP_COMMAND=/absolute/path/to/blender-mcp
SPATIAL_BLENDER_MCP_PYTHON=/absolute/path/to/python-with-mcp-installed
```

Credentials are checked in this order: `SPATIAL_BLENDER_API_KEY`, `GEMINI_API_KEY`,
`GOOGLE_API_KEY`, then the explicitly configured macOS Keychain service. The key is never
written to job artifacts, included in status responses, passed to the Blender worker, or
sent to the frontend. Selected video images **are sent to Google Gemini** for generation.
The original quick/balanced/high reconstruction modes still use local inference.

The official [Blender MCP server](https://www.blender.org/lab/mcp-server/) must expose
`execute_blender_code_for_cli`. Its Python interpreter needs the MCP SDK. The app's
`uv sync --locked` installs Google's SDK. Different community MCP servers may have
incompatible tool names.

Generated code is checked before execution and runs in a separate macOS sandboxed Blender
process. That process cannot access the network, read unrelated home-directory files,
write outside its job directory, or execute other programs. The worker executes only
geometry code; trusted scripts handle file saving/export. The user's interactive Blender
scene is not modified. Cancellation stops the API task or owned Blender process group.

The current generated-code worker is implemented and tested on macOS. On other platforms,
configure equivalent container isolation before enabling generated Python; the app currently
fails closed for this path. Existing `.blend`/`.glb` imports and the simple room-plan JSON
builder can still use `SPATIAL_BLENDER_TRANSPORT=headless` on supported Blender installations.

`GET /api/health` reports Blender availability, provider, model and video configuration.
The dashboard displays the selected model and external image-processing service.

The earlier optional OpenAI structured-room-plan provider is retained with
`SPATIAL_BLENDER_PROVIDER=openai`, its API key/model and optional
`SPATIAL_BLENDER_API_BASE`. That provider builds simple rectangular rooms from validated
JSON; it is not the active Gemini code-authoring route.

## API and files

`POST /api/scans` accepts multipart `file`, `name`, `mode` and `source`. Blender files automatically select the Blender provider. For video use `mode=blender`. Room-plan JSON is the strict schema in `backend/app/services/room_plan.py`; it is different from a full Sandbox JSON export, which should use **Import JSON** or `POST /api/scans/import`.

Per-job artifacts:

- `/api/scans/{id}/artifacts/model.blend` — generated/imported source model exported by Blender, before Sandbox edits.
- `/api/scans/{id}/artifacts/model.glb` — browser-ready source geometry/materials, before Sandbox edits.
- `/api/scans/{id}/artifacts/blender-scene.json` — source semantic geometry.
- `/api/scans/{id}/artifacts/gemini-generation.json` — model, selected frames, summary, assumptions and attempt count (no credentials).
- `/api/scans/{id}/artifacts/room-plan.json` — video-generated plan, when present.
- `/api/scans/{id}/artifacts/blender.log` — conversion diagnostics.
- `/api/scans/{id}/export` — portable application export containing **edited transforms and original model**. Use this for Sandbox edit round trips. Importing this JSON does not require Blender.

GLB assets are limited to 16 MB with embedded buffers/textures; the scene has the existing 500,000-vertex and 2,000-object limits. Unsupported/oversized files fail validation. Imported arbitrary geometry receives best-effort semantic labels from names; supply `spatial_kind` and `spatial_group` Blender custom properties for reliable grouping. Exported roots preserve `spatial_id`, `spatial_label`, `spatial_kind`, `spatial_cutaway` and frame indices through GLB round trips.

## Deployment boundary

The frontend builds as an ordinary Vite site. Blender/MCP and Python processing need a separate persistent worker/API environment with Blender installed, disk for jobs and the configured dependencies. A container can run the headless transport using the same scripts; this change does not include a verified container deployment. Frontend hosting alone will not run Blender. Keep this unauthenticated prototype local until deployment/authentication/job-storage work is done.

## Verification

Verified with the original `IMG_1328.MOV` café video on 2026-09-19: 154 frames decoded,
eight frames sent to Gemini 3.6 Flash, and the returned scene built through the actual
sandboxed Blender MCP path. The result contains 19 semantic groups covering booths, tables,
shelving, books, lights, walls, floor, ceiling and fixtures. Generation metadata and
assumptions are retained. No manual code correction was needed for that successful run.

The first live attempt encountered Gemini's 503 high-demand response; a later attempt
succeeded. The UI now reports that condition explicitly. This is a verified sample run,
not a guarantee that every clip or API request will succeed.

The generated café rendered at 60 FPS without browser errors. Selection, furniture movement,
undo/redo, persistence, original preservation, and JSON export/import all passed. Original
furniture placement was restored after verification. Screenshots and reports are in ignored
`test-results/gemini/`. The existing experiment script also passed through the new isolated
worker, producing its 190 mesh groups without a new API request.


- Real official MCP import of the provided lobby `.blend`, including procedural mural baking and ceiling/entry geometry.
- Actual MCP generation from a synthetic room plan with two doorways, couch and table.
- Actual GLB reimport preserved object IDs, semantic labels, cutaway flags and positions.
- Backend tests cover embedded asset integrity, immutable source data, portable export/import, worker cancellation/timeout, impossible layouts, missing vision configuration and frame-evidence validation.
- Browser checks and screenshots are written to ignored `test-results/blender/`.


### Visual review and correction

Generated scenes now retain separate surface/visibility groups and assembly-level door/elevator
labels. Browser recordings are read sequentially for selected images, with the original decoded
JPEGs retained if an enhanced-resolution pass cannot finish.

With `SPATIAL_BLENDER_VISUAL_REVIEW=true` (default), trusted Blender code renders three 640×480
cutaway views. Gemini receives the same selected source images, the renderings, and an object
inventory. It reports image-grounded discrepancies and a subjective visual-fidelity score.
At most one correction is generated, rendered and independently assessed. A valid correction
replaces the initial model only when its review score improves without increasing the issue count.
The baseline is preserved under `before-review/`; failed or worse corrections retain it. API
failures produce an explicit warning rather than discarding a usable model. Cancellation still
cancels the job. This adds up to three model calls (initial review, correction, second review)
and CPU rendering time, in addition to generation and any one compatibility repair.

`gemini-review.json` records the outcome, both assessments, and unresolved issues. The three
`review-view-N.png` artifacts show the chosen model. Review is not a guarantee of accuracy or
navigation safety. Set the flag false to skip these extra calls and renders for a faster draft.
