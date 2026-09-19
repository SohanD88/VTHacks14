# New demo video review — 2026-09-19

All four originals were processed through the real API at port 8016 and visually inspected in the Sandbox at port 5176. Originals are unchanged. No reconstruction code or navigation features were changed in this review.

**Result: the application works, but these outputs do not yet meet a clear, complete room-model quality bar.** IMG_1325 in Balanced mode is the strongest full-clip candidate. It shows a recognizable partial enclosure, floor, ceiling and two opening candidates, but substantial holes, folded floor geometry and incorrect object fits remain. Camera tracking percentages below are percentages of selected keyframes, not accuracy or room coverage.

| Input / mode | Processing | Tracked frames | Opening candidates | Visual assessment |
|---|---:|---:|---:|---|
| IMG_1323 / Balanced | 21.0 s | 13/48 (27.1%) | 1 | Entry fragment; most interior footage lost after the door transition. |
| IMG_1324 / Balanced | 15.0 s | 6/48 (12.5%) | 0 | Primarily the initial closed door and a floor patch. |
| IMG_1325 / Balanced | 19.2 s | 35/41 (85.4%) | 2 | Best full-clip result, but incomplete and visibly distorted. |
| IMG_1327 / Balanced | 18.2 s | 7/48 (14.6%) | 0 | Recognizable initial lounge furniture; the stairs and outside transition are not reconstructed as a continuous space. |
| IMG_1325 / High | 33.1 s | 41/56 (73.2%) | 1 | More geometry; still folded floor, wall holes and an oversized opening candidate. Not a clear quality improvement. |
| IMG_1324 interior 5–23 s / Balanced | 28.4 s | 27/48 (56.2%) | 3 | More interior recovered than the full clip, but warped floor/ceiling and missing walls remain. This separate trim excludes the entrance/exit transitions. |

All six results are explicitly marked degraded/partial. Opening candidates are not verified exits. No assumed door-width calibration was applied during this geometry comparison; global scale cannot repair tracking loss or distorted surfaces.

## Verified behavior

- Dashboard and Sandbox load all six actual reconstructions, with object counts matching the API.
- Cutaway, full-wall and observed-surface views checked; representative cutaway and full-wall screenshots visually reviewed against source contact sheets.
- Approximately 60 FPS in the tested desktop Chrome viewport; no page JavaScript errors.
- JSON export preserves the current and immutable original scenes exactly for each untouched reconstruction.
- Screenshot capture waits for rendering after inspector resize. Initial empty captures were replaced; no application renderer change was needed.

Artifacts are in `test-results/real-video/navigation-demo/`: original input metadata/contact sheets, manifests and complete scene results, browser verification JSON, screenshots, the separately named interior trim and reproduction scripts. `review.mjs` reviews the four originals; `review-comparison.mjs` reviews the two experiments; `compare_demo.py` creates the trim and submits new comparison jobs if rerun.

Best original result: http://127.0.0.1:5176/?scan=7c35102e-7538-421d-bfdb-b3f554afd233#modeler

The next capture experiment should start inside the room with doors already open, keep landscape orientation, and move slowly with overlapping views of stationary walls/furniture. This targets the observed tracking losses; it does not guarantee clean geometry from the current depth/fusion pipeline. Further geometry improvements require separate work beyond this quick test.
