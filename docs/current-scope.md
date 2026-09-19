# Current milestone agreed in the conversation

The user narrowed the original exhaustive reconstruction objective to a 1–2 hour basic-rendering milestone. Preserve existing video reconstruction and the Sandbox, add scale calibration using one doorway assumed to be 3.5 feet wide, verify persistence/export/import and existing behavior. Retain recognizable walls, floors, ceilings, furniture and opening candidates. Preserve data needed to build navigation later.

Do not add navigation annotations, pathfinding, LiDAR integration, or photorealistic polishing in this milestone. Do not continue open-ended ceiling/furniture reconstruction tuning. Scale is an assumption, not a measurement or accuracy guarantee. Do not force every doorway to the same width. Do not fabricate connectivity, walkable space or exits. Keep the old evaluation videos when new inputs arrive.

Changes: optional backward-compatible calibration metadata; proportional current object transforms and camera path; immutable original geometry/evidence; Sandbox two-point reference selection and assumed/measured basis; scale-aware dimensions; undo/redo/reset/remove-reference; export/import; URL-based active scan recovery on page reload. No new dependencies or sensing requirements.

Validation artifacts and remaining quality limitations are recorded in `real-video-review.md` and the scale-calibration result folder. The historical rendering quality caveats remain valid: missing surfaces, ambiguous furniture, pose/depth drift, and unverified exit function.

## Completion audit for this agreed milestone

| Requirement | Inspected evidence |
|---|---|
| Preserve video-derived walls, floors, ceilings, furniture and opening candidates | Both clips rerun through the real API; `scale-verification.json` proves exact pre-calibration scene equality to the prior reconstruction. Full-wall/cutaway screenshots visually reviewed. |
| Scale the room proportionally using one assumed 3.5 ft doorway | Sandbox two-point picker defaults to 3.5 ft; real meeting-room reference produces 1.074539× uniform scaling. Every mesh/observed world point and camera-path position verified numerically. |
| Clearly distinguish an assumption from a measurement | UI basis selector, persistent `calibration.basis`, generated `scale_note`, and exported reference metadata. Units remain estimated. |
| Preserve the original and future navigation inputs | Original JSON equality, immutable geometry/IDs/relationships/source frames, current transforms and camera path checked. No navigation inference or annotations added. |
| Saving, reload, editing, history, reset and export/import work | All 13 browser cases pass, including both real reconstructions and the new calibration failure/retry, undo/redo, reload, removal, reset, export/import and mobile checks. |
| Backend/frontend verification | 94 pytest cases, Ruff lint/format, TypeScript and production build pass. Results recorded in the verification logs. |
| New supplied videos, when available | Recursive file check found only the original two inputs. Their originals were retained; documentation identifies the optional navigation-demo folder for later inputs. |
| Reviewable handoff | Running isolated preview/API at 5176/8016; calibrated review copy `a309f63c-fae3-492a-b3e3-60b1d4d13f5d`. Screenshots, complete diagnostic archives, exported calibrated scene and numeric checks saved under `test-results/real-video/scale-calibration/`. |

This audit closes the narrowed Sandbox milestone, not a claim of precise building geometry or completed navigation. The user explicitly deferred further visual polishing, new sensing methods, annotations and pathfinding. Existing partial/degraded reconstruction labels and documented geometric limitations remain.
