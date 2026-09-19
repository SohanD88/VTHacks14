# Real-video evaluation · 19 September 2026

**Functional workflow verified; full geometric acceptance remains open.** Both inputs use actual frame-derived inference, poses and geometry. The latest viewer correction makes cutaway rendering and picking consistent and displays thin observed surfaces from either side. Scene data is unchanged. The preceding reconstruction iteration uses reciprocal image-mask evidence to prevent chair identity swaps during tracking. It preserves the lounge scene and all non-chair geometry in the meeting room. The preceding iteration fits the visible opening from observed jambs, lintel and depth discontinuities, with three-view validation and retained raw door geometry. The preceding wall-orientation iteration rejected cross-cutting plane artifacts and recovered a supported meeting-room corner. The preceding iteration fitted observed ceiling lights while preserving their raw geometry and editing protection. Earlier iterations corrected table width, seating orientation, source evidence, missed camera poses and observed wall planes. These improve particular failure modes; passing interaction tests does not establish physical accuracy.

## Sandbox scale milestone — latest verification

The user narrowed this pass to the existing basic 3D rendering, doorway-based room scale, and save/reload/export verification; navigation tools, LiDAR integration and further visual polishing are deferred. See `current-scope.md`. The earlier full-geometric-accuracy caveats below remain applicable.

The Sandbox now accepts two picked doorway-edge points and defaults to the user-assumed **3.5 ft / 1.0668 m** width. Calibration is optional and explicitly labeled assumed or user-measured. All current object positions/scales and camera-path positions change proportionally; mesh vertices, observed geometry, rotations, original transforms, IDs, source evidence and relationships are preserved. Applying the same reference twice does not compound the scale. Undo/redo, remove-reference, reset and JSON export/import preserve the correct state. Page reload now restores the active Sandbox scan via its URL.

Both original clips were reprocessed through an isolated API (8016) and viewed through its frontend (5176). Results are in `test-results/real-video/scale-calibration/` with verified full diagnostic archives. The lounge took **35.062 s**, the meeting room **19.745 s**; backend peak RSS was **965.0 / 1056.9 MiB**, with MPS enabled. Render samples were **60 / 61 FPS**. Counts remain **68 / 53 elements**, **0 / 1 opening candidates**, and **28/28 / 37/41 localized views**. The lounge's cold run includes cached model loading and concurrent browser validation; these are not controlled speed comparisons.

`review_scale.py` proves both new uncalibrated scenes exactly equal the prior mask-association scenes except the added null calibration field. A separate meeting-room copy uses the opening's observed jamb span (**0.992797 m**) as the scale reference: **1.074539×** yields the assumed **1.0668 m** clear width. All mesh and raw-observation world points and the camera path follow the same factor; the original reconstruction remains unchanged. This verifies mathematical consistency, not true building dimensions. The lounge has no supported doorway and is left uncalibrated.

Final checks: **94 backend tests passed in 9.76 s**, Ruff lint and formatting passed for **42 files**, frontend typecheck/build passed, and **13/13 browser tests passed in 1.7 minutes**. Both real-video workflows exercise rendering, hover/selection, editing, export/import and reset. The new calibration browser case additionally verifies picking, invalid width rejection, failed-save retry, history, persistence, mobile controls and structural protection. Full-wall, cutaway, calibrated, dashboard and mobile screenshots were inspected. The calibrated copy renders at **61 FPS** without page errors.

At this verification, only `IMG_1315.MOV` and `IMG_1319.MOV` were present. New demo videos can be added under `TestVideosOfRooms/navigation-demo/` and evaluated with the same discovery/API workflow. No source videos were replaced.

## Inputs and capture assessment

| Property | Lounge — IMG_1315.MOV | Meeting room — IMG_1319.MOV |
|---|---|---|
| Container / codec | MOV / HEVC | MOV / HEVC |
| Encoded / upright resolution | 1920×1080 / 1080×1920 | 1920×1080 / 1080×1920 |
| Upright aspect ratio | 9:16 | 9:16 |
| Duration / fps / frames | 6.0 s / 30 / 180 | 13.812 s / 29.9747 / 414 |
| Motion | Mostly lateral pan with a return view; little translation | Translation through an open door, then fast pan/tilt and return views |
| Smoothness and blur | Mostly usable; occasional pan blur | Pronounced blur/low texture during middle wall sweep |
| Lighting / exposure | Consistent interior light; sampled mean luminance 143–163/255 | Generally lit; sampled mean luminance 127–181/255; doorway occlusion and exposure change |
| Coverage / occlusion | Two seating sides, floor, ceiling, far window and artwork; furniture backs/legs partly occluded | Doorway, floor, walls, round table, chairs, window/blind and wall-mounted equipment; chairs occlude one another |
| Texture / repetition | Blank painted walls; carpet and repeated seats provide features; reflective window is unreliable depth | Blank walls, repeated chairs, carpet and doorway trim; blank sweep loses feature correspondences |
| Revisited views / parallax | Return views yes; weak baseline for measured geometry | Return views yes; entrance provides more translation but overlap breaks during sweep |
| Candidate / selected views | 45 candidate samples / 28 balanced / 45 high | 83 balanced candidates / 41 selected; 104 high candidates / 56 selected |

The candidate counts come from decoder quality reports. A low aggregate blur threshold does not imply every region is sharp: no sampled view was rejected solely as blurred in the final balanced run, even though localized motion blur is visible. The two clips use different sampling intervals and frame budgets based on duration. No filename enters inference or geometry generation.

Orientation-correct contact sheets and measured metadata are in `test-results/video-inspection/`. Regenerate with `backend/.venv/bin/python backend/scripts/inspect_videos.py --root .`.

## Previous mask-association balanced measurements

| Measurement | Lounge | Meeting room |
|---|---:|---:|
| Scan ID | daa8aaa0-ed69-4b65-873a-92bf15018c86 | 52ccdb55-1805-43e9-9a33-886215dc32f4 |
| Status | degraded | degraded |
| Total processing time | 26.330 s | 22.543 s |
| Average per decoded frame | 146.28 ms | 54.45 ms |
| Decoded / accepted / rejected | 180 / 28 / 152 | 414 / 41 / 373 |
| Keyframes / poses / failures | 28 / 28 / 0 | 41 / 37 / 4 |
| Semantic elements / opening candidates | 68 / 0 | 53 / 1 |
| Rejection reasons | sampling_interval: 135, keyframe_budget: 17 | keyframe_budget: 42, sampling_interval: 331 |
| Tracking acceptance / resets | 100.0% / 0 | 90.2% / 0 |
| Elements observed across multiple frames | 44 | 28 |
| Merged repeated observations | 340 | 359 |
| Depth / semantics / geometry | 2484 / 4297 / 7230 ms | 1877 / 4608 / 12564 ms |
| Process peak RSS | 818.5 MiB | 925.0 MiB |
| Execution device | mps | mps |
| Original scene JSON | 12,884,417 bytes | 15,977,065 bytes |
| Rendered mesh vertices | 68,569 | 96,494 |
| Whole-room coverage | Unknown; no reference map | Unknown; no reference map |

Machine: macOS 15.6 / Apple Silicon, 12 CPU cores, 16 GB RAM, Python 3.11.14, PyTorch 2.8 with MPS, Node 22.21. The first run loads cached weights; the second reuses resident models. Peak RSS is process-lifetime CPU resident memory, not isolated scan or GPU memory. Timings include decoding, inference, alignment, fusion and diagnostics before final artifact serialization; they are not upload-to-browser latency. JSON size excludes source media, diagnostics and edited export bundles. Tracking acceptance measures solver success, not ground-truth pose accuracy. Merged observations count fusion associations, not verified duplicate physical objects.

### Semantic outputs (model predictions)

**IMG_1315.MOV**: wall ×3 (mean confidence 0.862); unknown ×49 (mean confidence 0.525); floor ×1 (mean confidence 0.823); ceiling ×1 (mean confidence 0.968); rug ×2 (mean confidence 0.638); table ×2 (mean confidence 0.652); sofa ×2 (mean confidence 0.830); light ×2 (mean confidence 0.675); windowpane ×1 (mean confidence 0.776); coffee table ×1 (mean confidence 0.622); painting ×3 (mean confidence 0.790); ottoman ×1 (mean confidence 0.842).

**IMG_1319.MOV**: chair ×6 (mean confidence 0.835); wall ×3 (mean confidence 0.863); unknown ×33 (mean confidence 0.570); floor ×1 (mean confidence 0.915); ceiling ×1 (mean confidence 0.886); screen ×2 (mean confidence 0.961); light ×4 (mean confidence 0.703); door ×1 (mean confidence 0.618); table ×1 (mean confidence 0.666); curtain ×1 (mean confidence 0.934).


Confidence aggregates model scores, not calibrated probabilities of correct shape or identity. An element is a semantic surface or track, not necessarily a unique physical object. In particular, six fitted meeting-room chair tracks do not establish a complete or correct six-chair inventory. Small or ambiguous chair observations also remain in the uncertain layer.

## Reconstruction changes and measured tradeoffs

The hybrid approach uses metric indoor depth because the lounge is mostly a low-parallax pan and both rooms have textureless surfaces. SIFT/PnP provides camera motion; segmentation supplies surface semantics; instance detection separates furniture. It runs with the installed Apple MPS models without requiring a CUDA-only reconstruction stack.

Earlier iterations improved localization from one view to 28/28 lounge and 30/41 meeting-room views, replaced SegFormer B0 with B2, added RF-DETR instances, fitted recognizable furniture and grounded furniture to an observed floor. High quality was also processed (45/45 and 42/56 poses), but more samples alone did not remove layered walls. The high comparison is historical and predates the latest structural fit.

### Consistent cutaway rendering and selection

The previous renderer clipped walls and ceilings above 1.3 estimated meters but left linked artwork, window and screen surfaces visible above that height. These appeared to float after their supporting wall was cut away. Three.js raycasting also ignored the material clipping planes, so invisible upper wall faces intercepted clicks intended for visible furniture. A focused browser regression reproduced the failure: the hovered object was `wall` where the visible target behind it should have been selected.

Cutaway now applies the same plane to walls, ceilings and unedited surfaces linked to an existing wall. It preserves entrance markers and excludes user-modified attachments whose original boundary relationship may no longer describe their placement. Fully clipped groups lose labels, selection boxes and transform handles; changing layers clears stale hover feedback. Both meshes and point surfaces participate. Raycast hits must satisfy the same world-space clipping planes as rendering, allowing selection through removed wall sections.

Full-wall review exposed a second issue: back-face culling made the camera-facing room boundary disappear when viewed from outside. These meshes represent thin observed surfaces, not solids with reconstructed backs. Rendering the existing triangles from both sides restores those boundaries and the observed ceiling in full-wall mode. It does not add vertices, thickness, missing faces, or unobserved areas. Cutaway remains the useful default for inspecting furniture.

The new browser regression checks reverse triangle winding, selection through a partially clipped wall, hidden mounted artwork, visible freestanding artwork, restoration when cutaway is disabled, unchanged persisted scene data, and continued visibility after the user moves a previously mounted object. Existing real-video tests also verify editing, reset and export/import on both actual scans.

Current full-wall and cutaway screenshots are in `test-results/real-video/cutaway-review/`. They show that the room boundaries were more complete than the former one-sided rendering suggested, while actual gaps, noisy ceilings and uncertain geometry remain visible. The source scans, confidence values, geometry and processing measurements are unchanged from the mask-association iteration; no ML rerun is implied by these screenshots. The saved scene comparison confirms exact equality after browser verification. The latest modeler samples were 61 FPS for the lounge and 60 FPS for the meeting room.

### Image-mask evidence for instance identity

A source-frame audit found that the original distance-only association switched identities between the near and far right-hand chairs. Frames 245 and 275 assigned the same near chair to different tracks; frame 320 assigned those two tracks to distinct visible regions. The co-visibility merge guard correctly prevented a later blind merge, but the scene retained two nearly coincident fitted chairs. This was an association error, not evidence that the room should have a particular chair count.

`associate_instances` now combines normalized 3D distance (20% of the cost) with reciprocal projected-mask disagreement (80%). It samples at most 250 points per source surface and checks the last three observations of a candidate track. The lower of forward and reverse support is used for each comparison; the best recent supported view provides the score. The existing class-specific distance gate remains. A candidate up to twice that distance can match only when both masks support at least 55% of projected points. Out-of-frame and behind-camera points count as misses. Hungarian one-to-one assignment, unmatched observations and the separate co-visibility consolidation guard remain in force. These thresholds are heuristic; they do not establish physical identity in every occlusion or repeated-object scene.

The before/after source overlays are in `test-results/real-video/mask-association/chair-identity-evidence.jpg`. In the audited views the near chair now retains one track; the ambiguous far-chair fragment at frame 320 remains separate. The corrected exported object includes all 30 distinct source frames from the two previous overlapping objects. The meeting scene changes from eight fitted chair tracks to six, and from 56 total semantic elements to 53. Other uncertain chair surfaces remain. This is a correction to observed identity swaps, not validation of the room's true chair count.

`geometry-comparison.json` confirms identical camera paths, original/refined pose diagnostics and registration for both videos. The entire lounge scene is unchanged. Every non-chair object's geometry, transform, class, confidence, provenance and source frames is unchanged in the meeting room (generated numeric IDs may shift as chair groups change). Doorway, light, table and structural geometry are preserved.

The actual API reruns used isolated storage at `/tmp/vthacks14-chair-api`, API port 8015 and frontend port 5175 to avoid the shared scan quota. Latest results and screenshots are in `test-results/real-video/mask-association/`; full scan archives are retained there as `<scan-id>.tar.gz`. The older main `manifest-balanced.json` remains the opening-iteration baseline on port 8014. `evaluate_videos.py --output` and `REAL_VIDEO_RESULTS_DIR` now select comparison output without replacing that baseline.

Processing took 26.330 s for the lounge and 22.543 s for the meeting room on MPS. The lounge run included model loading and overlapped verification work; these are not controlled speed benchmarks. Geometry time was 7.230/12.564 s, compared with 7.308/10.664 s in the preceding run. Mask projection adds work in the instance-heavy meeting clip. Both modeler samples were 60 FPS. Browser inspection confirms that overlapping chair fits are reduced, while distorted walls and uncertain small surfaces remain.

Three additional regressions cover a centroid-induced identity swap and order independence, supported bounded depth drift versus distant aliases and co-visible exclusivity, and off-screen/behind-camera/empty projection rejection. No new dependency was added.

### Opening outline from observed jambs and lintel

The previous viewer built an axis-aligned portal using the largest horizontal extent of a fused door-class surface. In the meeting-room footage that surface is a thin door/jamb region along the side of the passage. Its depth extent became the displayed opening width, and its lowest observed point became the marker's base. This produced a marker running along the side of the doorway and floating above the estimated floor. The backend export contained the raw door surface rather than the outline shown by the viewer.

`openings.py` now proposes jamb/lintel combinations from color edges and signed depth discontinuities in source views already associated with a semantic opening candidate. It groups collinear edge fragments and tests up to 16 nearby outline hypotheses. A foreground vertical plane must have at least 75% support within 10 cm, with at least 60% support on each jamb and the lintel. Consensus is refitted before acceptance. The inferred outline must also agree in at least three localized views: each boundary needs nearby color edges, median foreground-depth error no greater than 20 cm, and at least 70% of samples showing a deeper interior by more than 35 cm. Visible floor inside the proposed passage is required. The lower edge is explicitly inferred from the observed floor; no unseen wall faces are added.

The original-pixel integration run exposed a difference from replaying compressed diagnostic JPEGs: edge segments were fragmented differently. A small Gaussian smoothing step stabilizes edge extraction, and bounded alternative hypotheses are evaluated using the same multi-view checks. The foreground-plane tolerance is 10 cm; the independent cross-view color/depth/gap gates remain in force. Candidates are chosen by supported-view count followed by measured boundary agreement, not by a preferred physical doorway size. The unsuccessful first pass is preserved under `opening-outline-first-pass/`.

The final meeting-room fit is supported by frames 10, 20 and 25. The semantic confidence remains unchanged; the new support is geometric evidence, not a recalibrated classification probability. The raw door vertices are retained within 4.5e-16 m of their original world coordinates; colors and triangle indices are unchanged. Source-frame references include the original segmentation views and the outline-validation views. The fitted opening remains an uncertain candidate, not a verified exit. Its supporting floor and observed wall-fragment boundary are linked in the metadata.

The displayed width changes from 1.806 m to a clear-width estimate of 0.993 m; the clear-height estimate is 2.912 m. The base moves from 0.845 m above the inferred floor to that floor plane. These are monocular estimates, not surveyed measurements.

The browser now draws the stored portal mesh, so JSON and PLY exports agree with the visible outline. The frame has jambs and a lintel, with no faces across the clear passage; its 4.5 cm stroke is a visualization thickness, not measured trim. **Observed surfaces** shows the retained door evidence. Structural movement/deletion protection remains enabled, including for screen-door candidates. Seven regression cases cover successful fitting and raw preservation, screen-door protection, single-view rejection, solid-door rejection, missing floor, windows, and unrelated semantic evidence. Browser checks validate the fit diagnostics, source references, clear passage, grounded base, protection, raw-versus-fitted views, and preservation of both geometries through export/import.

The lounge produces no new opening, and its scene remains unchanged. In the meeting room, all objects other than the opening remain unchanged, as do camera poses, registration, wall/corner fits, light fits and motion reports. Before/after geometry checks are in `test-results/real-video/opening-outline-results.json`; reproduce them with `backend/.venv/bin/python test-results/real-video/review_opening_outline.py`. `IMG_1319-opening-evidence.jpg` compares both outlines projected into the supporting source frames. Browser snapshots are `frontend/test-results/IMG_1319-balanced-opening.png` and `IMG_1319-balanced-opening-observed.png`. Full baseline scans/screenshots are archived under `pre-opening-outline/`.

This improves the observed rectangular doorway. It does not establish general entrance/exit completeness: occluded jambs, non-rectangular openings, missing floor evidence, insufficient overlapping views and inaccurate monocular depth can still prevent a reliable fit. Unaccepted candidates retain their prior approximate representation and uncertainty. Absolute dimensions remain estimated, and the floor-based lower edge is not a directly observed threshold.

### Wall fitting constrained by local surface orientation

The previous wall extractor used distance to a candidate plane alone. In the meeting room, two fitted planes cut across unrelated surfaces: only 6.4% and 11.7% of their raw triangle normals agreed within 25 degrees of the fitted normal. One spurious diagonal crossed the room interior. Position-only support had incorrectly promoted these observations into a coherent boundary.

`surface_normals` now accumulates area-weighted, unoriented triangle-normal covariance at each vertex. This tolerates inconsistent face winding. A normal is usable only when the dominant eigenvalue accounts for more than 75% of the local covariance; degenerate/isolated vertices cannot support a fit. RANSAC candidates require both the existing positional tolerance and a local normal within 25 degrees of the proposed vertical plane. Point-only inputs retain the positional path and do not claim orientation support. Unsupported mesh observations stay available as raw uncertain geometry.

Both full API reconstructions retain three fitted wall planes. Meeting-room fitted planes decrease from five to three, removing the two unsupported cross-cutting surfaces; its semantic-element count decreases from 58 to 56. The lounge retains three planes and 68 elements. Plane groups have median local-normal agreement of 0.966–0.997 (absolute dot product). Positional-plus-orientation support includes 42,618/52,498 lounge vertices (81.2%) and 38,194/67,499 meeting-room vertices (56.6%). These lower percentages reflect stricter evidence requirements, not lost observations or measured room coverage.

The existing corner algorithm now finds one supported meeting-room junction over height bins 0–30 on a 9 cm grid, adjusting 251 vertices by at most 0.2814 m. The lounge retains two junctions, now supported over bins 12–42 and 32–42, with 228/73 adjusted vertices and maximum displacements of 0.2727/0.2647 m. No faces are added to bridge unseen gaps. The other meeting-room corner remains incomplete.

The before/after audit preserves every raw wall vertex (maximum coordinate difference 5.0e-16 m), as well as identical furniture, floor, ceiling, camera poses, registration, motion reports and ceiling-light fits. Four lounge insets and two meeting-room screens move with the refined boundaries while keeping their raw geometry. The doorway's boundary reference updates; a curtain candidate no longer projects to a removed false plane. Its original surface remains available.

Top-down plots confirm that the meeting-room diagonal and interior parallel plane are absent; the new boundary better follows the retained raw surface directions. This is an internal consistency improvement, not an independent room survey. The lounge layout is nearly unchanged. The dashboard/modeler screenshots show the retained seating, tables, camera path and opening marker, with cleaner meeting-room side/far boundaries. They still show incomplete and noisy wall footprints, imperfect relative geometry and ambiguous furniture identity. Both modeler samples remain 60 FPS.

Total processing is 21.929 seconds for the lounge and 20.593 seconds for the meeting room on MPS. Geometry work is 7.579/10.619 seconds. Total scene vertices increase to 68,569/96,989 because more observations remain as uncertain raw geometry rather than compact fitted cells; scene JSON decreases to 12.88/16.00 MB because fewer observations are duplicated in fitted meshes. Raw uncertain geometry can still be toggled separately.

Three new regression cases reproduce a false plane spanning disconnected fins, verify winding/degeneracy handling, and preserve a meshed wall's door gap and raw faces. Real-video browser checks validate orientation-support diagnostics, preserved raw vertex counts, and the actual reported shared corner positions. The reproducible audit is `test-results/real-video/review_wall_orientation.py`, its results are `wall-orientation-results.json`, and top-down before/after figures are `IMG_1315-wall-orientation-comparison.png` and `IMG_1319-wall-orientation-comparison.png`. The full baseline scans and screenshots are archived in `pre-wall-normals/`.

### Ceiling-supported light patches

`fixtures.py` fits a ceiling plane only to repeatedly observed, confident ceiling geometry, requiring at least 60% point support within 10 cm and a sufficiently broad, near-horizontal surface. A nearby light must have at least three source views. Its source-camera rays intersect the observed plane only with bounded depth adjustment, non-grazing incidence and nearby observed ceiling support. Candidate patches preserve a real view's colors, triangles and holes. The acceptance check requires both projected-vertex inclusion and bidirectional silhouette coverage of at least 55% in three views and at least half of the available views. A convex hull is used only to compare image silhouettes; it does not create output faces. Among accepted candidates, the largest confidence-weighted observed patch is selected.

This replaces depth-stretched light surfaces with six compact patches: two in the lounge and four in the meeting room. Their longest dimensions change from 0.85/0.70 m to 0.27/0.34 m in the lounge, and from 1.21/0.90/0.60/0.70 m to 0.50/0.41/0.50/0.34 m in the meeting room. Supporting-view counts are 6/11 and 3/5/4/3. These are fitted estimates, not verified physical dimensions. A rejected first pass used inclusion alone and selected an undersized, partly occluded meeting-room patch; bidirectional coverage now rejects that failure. That intermediate output remains archived in `ceiling-fixtures-first-pass/`.

A conservative merge can join nearby fitted lights only when their source-frame sets are disjoint and both tracks have at least 55% median reciprocal mask support. It preserves all raw vertices/colors/triangles and updates object references. No merge passed in these real runs; a suspected duplicate pair remains separate. Co-visible candidates stay separate, including through successive merges. Unique fixture inventory remains unverified.

Accepted fixtures have `primitive_fitted` provenance, their ceiling's `supporting_surface` ID, retained `observed_geometry`, and structural editing protection. Thin light surfaces render from either side. The browser checks fixture metadata, plane consistency, source-image loading, and disabled movement/deletion until structural editing is enabled.

The saved comparison confirms all non-fixture objects, camera poses, registration, structural fits and motion reports are unchanged from `pre-ceiling-fixtures/`. Raw light vertices agree within 1.4e-17 m; their triangles, colors and source frames are preserved exactly. Displayed vertex counts change from 62,898/83,268 to 60,342/81,061; retaining the raw surfaces increases scene JSON from 13.14/16.59 MB to 13.30/16.82 MB. Total processing is 20.478/20.685 seconds on MPS. The browser samples remain 60 FPS.

Source-projection crops align with visible lights in the checked views. Dashboard and modeler screenshots show compact patches with visible protection and evidence metadata. The cutaway view hides the ceiling, so these patches appear suspended in that view. Ceiling support and dimensions remain model-based hypotheses; warped boundaries and uncertain nearby surfaces remain visible. Nine regression cases cover successful fitting, absent/vertical/unsupported ceilings, disagreement, undersized patches, transients, disjoint duplicate merging and co-visible separation.

`fixture-fit.json` records planes, selected views, per-frame support, extents and merges for each scan. `test-results/real-video/ceiling-fixture-results.json` records the before/after audit. Its reproduction script is `test-results/real-video/review_ceiling_fixtures.py`; the historical comparison requires the pre-wall-normal scans archived under `pre-wall-normals/`. The current wall-orientation audit separately verifies that these fixture fits remain unchanged. The corresponding `IMG_1315-ceiling-fixture-evidence.jpg` and `IMG_1319-ceiling-fixture-evidence.jpg` show projections into supporting source views. These image comparisons check alignment with model-derived masks, not independent geometric accuracy.

### Adaptive sampling of small observed surfaces

`sampling.py` samples eligible small semantic components at full pixel resolution when the coarse grid supplies fewer than 18 points. It uses the existing 0.32 pixel-confidence gate, considers components of 50–2,000 pixels, and retains at most 16 per view ranked by model support and area. Broad room structures, transient classes and the existing furniture-instance classes retain their original sampling. Candidate storage uses pixel indices rather than retaining full image masks for every discarded region. Triangles connect only observed neighboring pixels and reject edges longer than 35 cm, preserving holes and depth discontinuities.

Groups with finer observations use 1.5 cm voxel spacing and a 12-vertex emission minimum. The usual three-source-frame/0.6-confidence semantic gate still applies: unsupported surfaces remain unknown. Small components visible simultaneously cannot share a group. Every emitted object retains source frames and a method note. These are depth-derived surfaces, not inserted fixture assets or light-source effects.

The lounge now has two light-labeled groups supported by 11 and 19 frames; the meeting room has four supported by 4, 10, 6 and 4 frames. Source-frame projections align with visible ceiling lights. The meeting-room wall-mounted unit remains an uncertain light/lamp candidate. Finer sampling also retains other small uncertain surfaces and adds evidence to existing artwork/carpet regions. Total semantic elements rise from 33/32 to 68/58, predominantly because unknown surfaces increase from 16/12 to 49/34. These are semantic components, not newly verified physical-object counts.

Furniture fits, wall/floor/ceiling geometry, camera poses and registration are unchanged. One lounge artwork surface receives more observations and changes shape; a previously confident mirror region becomes uncertain. The pre-ceiling-fit runs took 20.989/20.876 seconds on MPS. Displayed vertices rise from 53,338/76,389 to 62,898/83,268, and JSON size from 12.46/16.11 MB to 13.14/16.59 MB. Browser samples remain about 60 FPS.

This recovered missing fixture evidence before the ceiling-fit iteration above. Depth drift stretched the six raw light patches to approximately 0.6–1.2 m along their longest dimension. Two meeting-room groups may represent the same light across disjoint views. Their exact dimensions, unique inventory and attachment to the ceiling remain unverified. The raw geometry and uncertainty are retained; source projections should not be mistaken for proof of accurate 3D depth.

Five regression cases cover repeated small lights, single-view uncertainty and low-confidence rejection, large-region/tiny-noise exclusion, holes/depth jumps, and nearby co-visible fixture separation. The real-video browser tests select a recovered light and load its source images. `test-results/real-video/small-surface-results.json` lists every adaptive component and evidence frames. `IMG_1315-small-surface-evidence.jpg` and `IMG_1319-small-surface-evidence.jpg` show projected patches in first/middle/last supporting frames; `review_small_surfaces.py` records the historical pre-ceiling comparison and requires its archived scan data to reproduce it; use `review_ceiling_fixtures.py` for the current iteration. Previous scans/screenshots are in `pre-small-surfaces/`.

### Table width from component-specific observations

Disconnected semantic surfaces previously shared one width estimate for their entire group. A smaller table could inherit a larger table's width from different frames, or the image span across both surfaces in a shared frame. The fit now selects each component's contributing raw vertices through the voxel mapping, projects only those points back into their source camera coordinates, and computes that component's per-view apparent widths. It retains the existing 80th-percentile aggregation and dimensional bounds. Tracked instances still use their selected observed snapshot.

Two regression cases reproduce width contamination across separate observations and inside a shared observation: 0.8 m and 1.6 m surfaces previously both became 1.6 m or 2.7 m wide. Both now retain their individual supported widths. In the archived width-correction run, semantic table `element-0012` changed from 1.374 × 0.850 × 1.015 m to 1.056 × 0.850 × 1.015 m. Its shape is less stretched and closer to the other visible pedestal tables, but the dimensions remain monocular estimates. The meeting-room geometry is unchanged. Both runs retain exactly the previous observed world coordinates, source frames, camera poses, registration and structural fits.

Before/after dimensions and evidence checks are in `test-results/real-video/component-width-changes.json`; previous scans and screenshots are archived in `test-results/real-video/pre-component-widths/`.

### Small-fixture sampling audit (baseline)

The saved full-resolution semantic masks contain 33 lounge and 44 meeting-room light/lamp regions of at least 50 pixels in successfully localized views. At the current five-pixel sampling step, all 33 lounge regions and 40 meeting-room regions have fewer than the required 18 samples, so they cannot reach semantic surface construction even before confidence filtering. This identifies a concrete sampling loss upstream of scene fitting. The counts are repeated 2D regions, not unique fixtures or verified labels; some larger meeting-room light/lamp regions correspond to a misclassified wall-mounted unit. The adaptive sampling iteration above addresses this sampling loss; geometric identity and shape verification remain necessary.

The baseline audit is saved in `test-results/real-video/small-surface-audit.json` with source scan IDs, frame numbers, mask bounds, pixel counts and tracking status. Its reproduction script is `test-results/real-video/audit_small_surfaces.py`.

### Seating orientation after table merging

Previously seating used every candidate table center before duplicate table surfaces were removed. Five meeting-room chairs therefore faced a semantic table fragment that was absent from the saved scene. Table fitting and overlap merging now happen first. Static seating uses the surviving static table centers; moving tables cannot steer permanent seating. The overlap merge also restricts coffee tables to the table family, rather than allowing a coffee-table surface to merge into an overlapping chair.

Both full API runs retain the same objects, source frames, camera poses, registration and structural fits as the previous iteration. The lounge has no geometry changes. Five meeting-room chair yaws change by 3.99–10.25 degrees, bringing their fitted fronts toward the surviving main table. The measured maximum change in retained observed world coordinates is 4.44e-16 m (floating-point roundoff). These orientations remain an explicit furniture-layout heuristic, not measured chair facing directions; chairs in other rooms need not face a table. Physical orientation accuracy remains unverified.

Five regression cases cover duplicate removal independent of object ordering, a genuinely distinct nearby table, moving-table exclusion, and coffee-table/chair separation. They check that the retained observed surfaces and original transforms remain consistent. Full before/after scans and screenshots are archived in `test-results/real-video/pre-seating-orientation/`; `test-results/real-video/seating-orientation-changes.json` records all affected IDs, angles and geometry checks.

### Component-specific source evidence

A semantic group can split into disconnected 3D components. Previously every emitted component inherited all group source frames and the mean of all group observation scores, even when most of those observations belonged to another component. Voxel fusion now retains the raw-to-fused vertex mapping. Each static semantic component gets only the frames and observation scores that contributed its vertices. Instance tracks and moving snapshots retain their matched track evidence. The existing three-frame/0.6 semantic reliability gates now use that component's actual support.

Real output comparisons identify five changed surviving objects in the lounge and two in the meeting room. A lounge table fragment goes from four cited frames to its one real frame, and a meeting-room table fragment from six to one. The lounge's smaller sofa candidate drops from 12 cited frames to five and from 0.641 to 0.574 confidence, becoming uncertain observed geometry. One rug fragment also becomes uncertain. Subsequent existing fitting/deduplication changes total element counts to 33/32 and sofa fits to two; all three lounge table fits and eight meeting-room chair fits remain. No camera pose or depth prediction changes in this iteration.

Four regression cases cover disconnected single-frame evidence, confidence isolation, components actually sharing frames and raw-to-voxel mapping. The old implementation fails the source-attribution cases; the corrected implementation passes. Actual before/after frame lists and scores are saved in `test-results/real-video/surface-evidence-changes.json`. Previous scenes/screenshots/full scan directories are preserved in `test-results/real-video/pre-surface-evidence/`.

### Fixture classifier experiment (not adopted)

The installed ADE20K segmentation vocabulary contains light, lamp, screen and radiator classes but no air-conditioner class. An offline trial compared 147 observed image regions from both videos (84 lounge, 63 meeting room) against the existing class vocabulary plus ten fixture/background candidates using [CLIP ViT-B/32](https://huggingface.co/openai/clip-vit-base-patch32). The model card describes image/text similarity classification and cautions that category choices affect performance; these scores are not calibrated probabilities of a physical object.

CPU inference ranked air conditioner first on only one region. Small partial crops often favored unrelated classes, and lounge artwork sometimes resembled a ventilation grille. CPU and MPS top labels disagreed on all 147 regions in this PyTorch 2.8.0 / Transformers 5.17.0 environment. Explicit eager attention produced the same GPU rankings. An identical air-conditioner crop with six candidate labels scored air conditioner 0.736 on CPU, while MPS scored arcade machine 0.906. This demonstrates a runtime discrepancy, not its root cause. CPU region inference took 3.62 seconds after loading; that excludes downloads and startup.

The trial is rejected for automatic scene relabeling. No CLIP model or new package is required by the application; the downloaded experimental weights are only cached locally. Scripts, crops, CPU/GPU rankings, comparison statistics and the sanity-check log are in `test-results/fixture-classifier-experiment/`. Fixture recognition remains incomplete and requires stronger localization/context and validation; model vocabulary extension alone does not fix it.

### Recovery of missed camera poses (previous iteration)

`relocalization.py` searches accepted views using reciprocal SIFT matches after the forward pass. Each candidate requires at least 20 PnP inliers, at least 50% inlier support, image-space spread, positive depths and bounded reprojection. Two reference estimates must agree within 20 cm, 0.06 radians and 0.12 in log depth scale. Up to three passes let supported recovered views help adjacent views, while keeping every view connected to the original coordinate system. Unverified views are excluded; no pose is interpolated. Cancellation is checked during matching. `camera-poses.json` records recovery method, references, pass, inliers and depth scale.

The camera-recovery API rerun recovered meeting-room frames 120, 125, 135, 145, 160, 210 and 220. Acceptance rises from 30/41 (73.2%) to 37/41 (90.2%), with four failures remaining. That recovery-only comparison left lounge geometry unchanged at 28/28 poses. The subsequent component-evidence correction below changes its confidence and one furniture fit. Recovery introduces no new dependencies. Meeting-room processing increases from 16.149 to 19.747 seconds on this run; the lounge takes 20.296 seconds with a cold model load.

The recovered views add visible left-wall and floor observations. They include the wall-mounted unit, but segmentation confuses parts of it with screen/light surfaces; recovery alone does not solve fixture classification. Chair tracks increase from seven to eight and screen tracks from one to two, so higher pose acceptance is not evidence of a correct unique inventory. The browser render still has incomplete wall boundaries and uncertain relative positions. Five recovered views depend largely on other recovered views; supporting-reference agreement is not independent ground truth. Joint refinement improves internal consistency but cannot establish physical accuracy.

Five new unit tests check known-camera pose/scale recovery, insufficient support, disagreeing references, narrowly distributed features and cancellation. Both actual browser tests check recovered-pose references, counts and source-frame presence in emitted geometry, then exercise editing/export/import/reset. The prior unedited results, complete scan directories and screenshots are archived in `test-results/real-video/pre-relocalization/`.

### Joint registration

`registration.py` matches nearby and return-view SIFT features and jointly adjusts accepted camera poses and per-view depth scales using bounded sparse robust least squares. The origin remains anchored. It uses symmetric reprojection, 3D consistency and conservative priors. It accepts a result only if median 3D residual improves and median reprojection does not worsen by more than 5%. It never creates poses for failed views. This is a bounded pose/depth refinement, not full bundle adjustment or a complete SLAM system.

| Measure | Lounge | Meeting room |
|---|---:|---:|
| Matched graph edges / features | 147 / 11326 | 191 / 11477 |
| Median 3D residual, before → candidate | 0.0772 → 0.0782 m | 0.1295 → 0.1245 m |
| Median reprojection, before → candidate | 0.944 → 0.919 px | 1.356 → 1.209 px |
| Refinement applied | No; original accepted poses retained | Yes |

The meeting-room residuals improved by approximately 3.8% in 3D and 10.8% in image space. These are internal feature-consistency measures, not ground-truth accuracy. The lounge candidate worsened the 3D measure and was rejected. Registration diagnostics retain both measurements.

### Observed wall fitting

`surfaces.py` robustly estimates vertical planes, merges nearby parallel estimates and builds shared-vertex cells only where wall observations exist. It preserves holes rather than using a convex hull to close a room. Nearby window/screen/curtain/artwork surfaces are aligned to their observed boundary plane. Raw surfaces remain available through **Observed surfaces**; unsupported wall points remain in the uncertain layer. Every fitted surface retains provenance and source frames.

- IMG_1315.MOV: 3 planes, 42,618/52,498 wall vertices supported by position and orientation (81.2%), 4 aligned inset surfaces.
- IMG_1319.MOV: 3 planes, 38,194/67,499 wall vertices supported by position and orientation (56.6%), 2 aligned inset surfaces.

These percentages measure agreement with the model's own observations, not room coverage or physical wall accuracy. Historically, the camera-recovery iteration increased meeting-room wall observations from 48,270 to 67,499 vertices; supported wall observations increase from 41,551 to 57,664. Its displayed scene grows from 69,371 to 76,435 vertices and scene JSON from 13.46 MB to 16.12 MB, including retained raw geometry. Geometry processing rises from 7.80 to 10.85 seconds. The camera-recovery-only comparison left lounge geometry unchanged; the latest component-evidence correction affects its semantic geometry as described below.

### Instance association and furniture

The latest `tracking.py` uses a gated, class-aware, one-to-one assignment across all detections in a frame. The previous first-match loop could consume a track needed by another nearby chair and depended on detection order. Regression tests reproduce that failure. Separate instances observed simultaneously cannot receive the same track; unmatched observations remain separate. Existing class-specific distance gates are preserved rather than relaxed to force a preferred chair count.

The consolidation stage additionally consolidates disjoint tracks using reciprocal projection of their observed 3D surfaces into each other's source-frame instance masks. It compares up to three well-observed views per track, checks class, distance and appearance, and requires at least 55% median mask support in both directions. Tracks seen together cannot merge, including through an intermediate track. Merging retains every observation and correctly rebases triangle indices. `instance-tracks.json` records each merge's track references, source frames and measured overlap.

Before camera recovery, consolidation reduced meeting-room chair fits from nine to seven and total scene elements from 32 to 29. The camera-recovery views produced eight chair tracks and 33 scene elements; the latest evidence correction retains eight chair tracks and 32 elements; the additional track is not independently verified as a unique chair. Four merges joined two fragmented chair identities (including short uncertain tracks), removing two duplicate chair fits and one uncertain fragment. Reciprocal support for the accepted pairs ranged from 57.1% to 93.0%. The lounge remained unchanged, with three sofa fits and three pedestal-table fits. The unchanged lounge also provides a regression check against indiscriminate merging. A nearby remaining pair had only 34% support in one direction in the exploratory replay and was preserved. The algorithm does not aim for a predefined chair count.

A reciprocal SIFT-feature association experiment was also tried on saved observations. It did not produce a reliable improvement and was not adopted. The replay was an association diagnostic, not a replacement for model inference; the final measurements above are from both full API reconstructions with the actual models. The pre-consolidation scans, results and screenshots are archived in `test-results/real-video/pre-consolidation/` for comparison.

### Observed corner connections

The wall meshes use independent observed-cell grids, which left seams even where neighboring walls approached their fitted intersection. `join_observed_corners` now aligns edge vertices within 30 cm of that intersection, only across at least four consecutive height bins observed on both wall boundaries. Parallel planes, distant edges, internal crossings and unsupported height gaps are left unchanged. It adds no faces, removes degenerate triangles, retains every raw observation, and stores reciprocal `adjacent:<wall-id>` relationships. These remain explicitly fitted, approximate corners rather than measured construction geometry.

In the earlier position-only lounge run, two supported corner sections were joined. The first adjusted 48 vertices across height bins 10–15 on a 9 cm grid; the second adjusted 151 across bins 11–32. Maximum adjustments were 0.294 m and 0.2858 m. Other height ranges remain incomplete. That earlier meeting-room run did not satisfy the matching edge-support criteria. The local-orientation iteration above now supports one meeting-room junction. In the earlier corner-only iteration, comparison with `pre-corners/` confirmed unchanged furniture, floor, camera trajectory and raw surfaces; later camera recovery changes those observations.

Unit tests verify that the meshes share corner positions while preserving a missing height band, and reject distant, parallel or internally crossing surfaces. Real-video browser checks also verify actual shared mesh positions at the reported corners, provenance and adjacency metadata. `structure-fit.json` records the corner intersections, supported height bins, adjusted vertex counts and maximum displacement. The pre-change scans, results and screenshots are preserved under `test-results/real-video/pre-corners/`.

### Moving-object evidence and separate layer

`motion.py` reuses the SIFT features and refined camera poses already produced by reconstruction. Reciprocal descriptor matches are checked against relative-camera epipolar geometry (or rotation reprojection at negligible translation) and depth-based reprojection. This follows the camera constraints described in [OpenCV's epipolar geometry documentation](https://docs.opencv.org/4.12.0/da/de9/tutorial_py_epipolar_geometry.html). The motion decision requires six matching object features, at least 30 background matches, low background residuals, at least 75% object outliers, and two consecutive supported frame pairs. Thresholds are measured in inference-image pixels. The epipolar test prevents depth-scale noise alone from triggering a moving flag.

A flagged track retains one observed snapshot with `transient: true`; it is not fused across changing positions or replaced by a stationary furniture fit. **Moving candidates** is a separate, initially disabled layer in the modeler. Metadata states that it is a moving candidate, and the flag survives export/import. Human/animal/vehicle semantic masking remains in place. `motion-report.json` records assessed groups, source frames, output IDs, residuals, background checks and status. Groups discarded by mesh-quality or duplicate handling can have no surviving output object; report-group counts are not scene-object counts.

Both supplied clips contain no obvious independently moving room objects. The latest runs produce zero moving flags. The latest lounge motion report has 5 consistent, 51 insufficiently verified and 5 structural groups; the meeting room has 4, 47 and 6 respectively. “Consistent” means no supported motion residual in assessed views, not proof that an object never moved. The historical motion-only iteration left both scenes unchanged relative to `pre-motion/`; the camera-recovery iteration changes meeting-room geometry while leaving the lounge unchanged.

Controlled geometric tests cover a moving object viewed by moving and stationary cameras, a static object with camera translation plus changing depth scale, sparse evidence, an inaccurate camera/background model, and moving-object snapshot output through fusion. They also explicitly demonstrate a blind spot: motion that remains on an epipolar line can evade the check. A separate browser fixture verifies hidden/default versus enabled layer visibility using actual raycasting and preserves the flag through export/import. Its screenshot is `frontend/test-results/moving-candidate-layer.png`; it is a controlled UI fixture, not a third real-room reconstruction.

This implements evidence-based moving candidates, not complete motion segmentation. Sparse texture, occlusion, rapid movement that splits tracks, camera errors, and motion consistent with the epipolar geometry can remain undetected. Camera poses are not refitted after a moving candidate is identified, so foreground-dominated motion can still undermine the initial camera estimate. Stronger real-world moving-object validation is still needed; the two supplied static clips establish only a false-positive regression check.

## Visual review against source footage

### Lounge

The two main brown seating sides and three white pedestal tables remain recognizable, with fitted seats/backs/arms/feet and table tops/supports. A smaller third sofa candidate now retains its observed surface in the uncertain layer instead of a confident furniture fit: its actual component support is five frames, and its mean confidence is 0.574 rather than the inherited 0.641. This removes an unsupported semantic promotion but makes that seating section less recognizable in the default view. The raw surface remains available for inspection; better instance/semantic evidence is still needed to recover it reliably. Window/artwork labels and raw fragments remain uncertain. No entrance was detected; this is not evidence that the room lacks an exit.

### Meeting room

The doorway approach, green wall band, round table, chairs, carpet and far blind/screen are recognizable. The amber doorway portal now follows a three-view-supported jamb/lintel fit, is grounded on the inferred floor, and is protected and exported with boundary metadata. Its scale, lower threshold and whether it is an exit remain uncertain. Four selected views (165, 175, 185 and 200) in the blank-wall sweep still fail localization and are excluded; seven formerly lost views now contribute observed surfaces. The fitted far screen and walls are flatter than the pre-planar result, but corners, scale and chair placement are still imperfect. Six fitted chair tracks now remain after the image-mask association correction. Ambiguous chair fragments remain separately visible in the uncertain layer. Their count and identities are not a verified physical inventory. Ceiling-light patches are now fitted to supported ceiling geometry and retain their raw evidence, while unique fixture identity, verified dimensions and the wall-mounted unit remain unresolved.

The floor near the dominant observed plane is stable; furniture fits use that support. Unseen floor regions stay absent. Other elevations and outliers are preserved rather than flattening all geometry indiscriminately. Raw geometry may still contain fragments. Feature-supported moving tracks are now separated from permanent geometry. The static supplied clips did not trigger that layer; general motion recovery remains limited by feature support and camera geometry.

## Saved evidence

- `TestVideosOfRooms/IMG_1315.MOV` → `daa8aaa0-ed69-4b65-873a-92bf15018c86`; SHA-256 `8e5f8c3a2ff2fdfd685a7f1db7422b98fdf1d6a0db295642f3437df13fe2d4f8`. API result: `test-results/real-video/mask-association/IMG_1315-8e5f8c3a-balanced.json`. Screenshots and metrics: `test-results/real-video/mask-association/IMG_1315-balanced-*`. Modeler sample: 60 FPS; editing/export/import/reset verified.
- `TestVideosOfRooms/IMG_1319.MOV` → `52ccdb55-1805-43e9-9a33-886215dc32f4`; SHA-256 `cad6c721131e85230cce5723fb1082340b498121b1da885a6773b43a1c886c51`. API result: `test-results/real-video/mask-association/IMG_1319-cad6c721-balanced.json`. Screenshots and metrics: `test-results/real-video/mask-association/IMG_1319-balanced-*`. Modeler sample: 60 FPS; editing/export/import/reset verified.

Each full scan archive contains source media, selected frames, quality reports, detection JSON/overlays, masks, original/refined depth and poses, registration, structure/fixture/opening fits, instance/motion reports, PLY, original/current scene JSON and metrics. Source images are not embedded in exported scene JSON.

Earlier results remain in `test-results/real-video/`, including the preceding opening-fit manifest and `opening-browser-evidence/`, and archived structural, fixture, motion and registration comparisons. No existing user scan was deleted for this iteration.

## Verification and acceptance status

Backend: **89 tests passed in 11.78 s**; Ruff lint and formatting passed for all 40 files. Frontend TypeScript and production build passed. The latest complete browser suite passed **12/12 in 1.3 minutes**, including both existing real scans and the new cutaway regression, using isolated storage. The earlier opening-iteration run had two import failures from the shared 20-scan limit; those were separately rerun successfully. The isolated full runs avoid that contention. Exact commands are in `test-results/backend-verification.txt` and `test-results/frontend-verification.txt`. Current dashboard/modeler and full-wall/cutaway screenshots were visually reviewed and retained in `test-results/real-video/cutaway-review/`; the earlier reconstruction comparison remains under `mask-association/`. Backend code is unchanged since its 89-test verification; this iteration reran frontend checks and browser tests.

Interaction coverage includes upload/retry/progress/cancel, camera recording, navigation, real-scene rendering, hover/click, metadata, movement/rotation, deletion/history/reset, protected structures, export/import, dashboard synchronization, mobile layout and WebGL fallback. Real-video checks fetch the alignment/structure diagnostics and switch between fitted and observed geometry. Synthetic API/browser fixtures test contracts and are never presented as reconstruction evidence.

**Still open:** reliable unique physical-object inventory, connected wall corners, consistently accurate relative placement/orientation, general dynamic-object exclusion and complete visible fixtures/small-object recovery. The videos have no calibrated intrinsics, measured reference distances or complete room survey. The algorithm lacks full landmark bundle adjustment and dense general motion segmentation; its new sparse-feature motion check has explicit unverified cases. These are concrete data/algorithm limitations, not an unavailable GPU: actual MPS inference works. This report does not claim full geometric acceptance.

Next quality work should address the remaining boundary gaps and pose/depth drift, investigate ambiguous chair identities using additional views, and recover missing visible fixtures. Nearby supported corner seams are now joined; the remaining meeting-room boundaries require stronger pose/depth evidence rather than larger arbitrary gap filling. Reciprocal projection consolidation now handles supported disjoint-track merges; remaining uncertain cases stay separate. Do not merge nearby chairs merely to match an expected count or close unobserved walls to make the render look complete.

Setup, commands, processing modes, export behavior and troubleshooting are in the README. The legacy root static deployment is not the validated application; a hosted service needs separate Python compute/storage. The installed Sites skill describes a Cloudflare Workers runtime with 128 MB per isolate; the validated native Python/OpenCV/PyTorch pipeline uses roughly 0.8–0.9 GiB CPU resident memory plus accelerator memory and cannot run in that static/Worker configuration. No externally hosted inference endpoint is configured. No static-only publication is represented as a working reconstruction service.
