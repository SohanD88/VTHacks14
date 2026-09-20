"""Validated upload, polling, artifacts, versioned editing and portable imports."""

import asyncio
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.schemas import CalibrationEdit, Mode, ScanResponse, Scene, SceneEdit, TransformEdits
from app.services.calibration import apply_calibration, same_transform, validate_edit
from app.services.store import TERMINAL
from app.services.video import EXTENSIONS, ProcessingError, metadata

router = APIRouter(prefix="/api/scans", tags=["scans"])


def require(request, id, include_scene=True):
    scan = request.app.state.scan_store.get(id, include_scene=include_scene)
    if not scan:
        raise HTTPException(404, "Scan not found. Select a saved scan or upload the video again.")
    return scan


@router.get("")
def list_scans(request: Request):
    store = request.app.state.scan_store
    with store.lock:
        return [
            s.model_dump(mode="json", exclude={"scene"})
            for s in sorted(store.scans.values(), key=lambda s: s.created_at, reverse=True)
        ]


@router.post("", status_code=202, response_model=ScanResponse)
async def create_scan(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form("Room scan"),
    mode: Mode = Form("balanced"),
    source: str = Form("video"),
):
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(422, "Scan name must contain 1–80 characters.")
    if source not in {"video", "capture"}:
        raise HTTPException(422, "Invalid input source.")
    suffix = Path(file.filename or "").suffix.lower()
    is_model = suffix in {".blend", ".glb", ".json"}
    if is_model:
        mode = "blender"
    if mode == "blender":
        try:
            request.app.state.blender.executable()
        except ProcessingError as exc:
            raise HTTPException(503, str(exc)) from exc
    if suffix not in EXTENSIONS and not is_model:
        raise HTTPException(
            415, "Unsupported format. Use MP4, MOV, WebM, AVI, MKV, .blend, .glb or room-plan JSON."
        )
    store = request.app.state.scan_store
    try:
        scan = store.reserve(request.app.state.settings.max_upload_bytes + 256 * 1024**2)
    except ProcessingError as exc:
        raise HTTPException(429, str(exc)) from exc
    path = store.directory(scan.id) / f"input{suffix}"
    try:
        size = 0
        with path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > request.app.state.settings.max_upload_bytes:
                    raise HTTPException(
                        413,
                        (
                            "File exceeds the upload size limit (default 250 MB). Simplify or com"
                            "press it."
                        ),
                    )
                output.write(chunk)
        if not size:
            raise HTTPException(422, "Upload is empty. Select a nonempty file.")
        info = (
            None
            if is_model
            else await asyncio.to_thread(
                metadata, path, Path(file.filename or "capture").name[:150]
            )
        )
        scan.name = name
        scan.processing_mode = mode
        scan.source = "import" if is_model else source
        scan.video = info
        scan.stage = "queued"
        provider = (
            request.app.state.blender if mode == "blender" else request.app.state.reconstruction
        )
        store.submit(scan, path, provider)
        return scan.model_copy(deep=True)
    except (ProcessingError, HTTPException) as exc:
        path.unlink(missing_ok=True)
        scan.status = "failed"
        scan.error = str(exc)
        scan.message = "Upload validation failed"
        store.save(scan)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, str(exc)) from exc
    except asyncio.CancelledError:
        path.unlink(missing_ok=True)
        scan.status = "cancelled"
        scan.message = "Upload connection closed. Submit the selected video again."
        store.save(scan)
        raise
    finally:
        await file.close()


@router.post("/import", status_code=201, response_model=ScanResponse)
async def import_scan(request: Request):
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 80 * 1024**2:
            raise HTTPException(413, "Scene import exceeds 80 MB.")
        chunks.append(chunk)
    try:
        data = json.loads(b"".join(chunks))
        scan = ScanResponse.model_validate(data["scan"])
        original = Scene.model_validate(data["original"])
        if scan.scene is None or data.get("format") != "spatial-scene-v2":
            raise ValueError("Missing scene or version")
        validate_edit(original, scan.scene)
        # Imported provenance is preserved but explicitly identified as imported data.
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(
            422,
            "Invalid scene export. Import a version 2 export from this application.",
        ) from exc
    store = request.app.state.scan_store
    try:
        reserved = store.reserve(size * 2)
    except ProcessingError as exc:
        raise HTTPException(429, str(exc)) from exc
    scan.id = reserved.id
    scan.source = "import"
    scan.status = "degraded"
    scan.stage = "finished"
    scan.progress = 100
    scan.revision = 0
    scan.warnings.append(
        (
            "Imported scene: provenance and geometry supplied by the export fi"
            "le; not reverified against a video."
        )
    )
    store.atomic(store.directory(scan.id) / "original.json", original.model_dump_json())
    store.save(scan)
    return scan


@router.get("/{scan_id}", response_model=ScanResponse)
def get_scan(scan_id: UUID, request: Request):
    return require(request, scan_id)


@router.get("/{scan_id}/status")
def status(scan_id: UUID, request: Request):
    return require(request, scan_id, include_scene=False).model_dump(mode="json", exclude={"scene"})


@router.post("/{scan_id}/cancel")
def cancel(scan_id: UUID, request: Request):
    scan = require(request, scan_id)
    if scan.status in TERMINAL:
        return {"status": scan.status}
    if not request.app.state.scan_store.cancel(scan_id):
        raise HTTPException(409, "Job is no longer running. Refresh its status.")
    return {"status": "cancelling"}


@router.delete("/{scan_id}")
def delete(scan_id: UUID, request: Request):
    require(request, scan_id)
    try:
        request.app.state.scan_store.delete(scan_id)
    except ProcessingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": True}


@router.get("/{scan_id}/original", response_model=Scene)
def original(scan_id: UUID, request: Request):
    require(request, scan_id)
    scene = request.app.state.scan_store.original(scan_id)
    if not scene:
        raise HTTPException(409, "Original reconstruction is not available yet.")
    return scene


@router.put("/{scan_id}/scene", response_model=ScanResponse)
def save_scene(scan_id: UUID, body: SceneEdit, request: Request):
    store = request.app.state.scan_store
    with store.lock:
        scan = require(request, scan_id)
        if scan.scene is None or scan.status not in TERMINAL:
            raise HTTPException(409, "Wait for a reconstruction before editing.")
        if body.revision != scan.revision:
            raise HTTPException(
                409,
                "Scene changed in another session. Reload the saved scan before editing.",
            )
        original = store.original(scan_id)
        try:
            validate_edit(original, body.scene)
            previous_scene = apply_calibration(scan.scene, body.scene.calibration, original)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        previous_objects = {o.id: o for o in previous_scene.objects}
        for obj in body.scene.objects:
            previous = previous_objects[obj.id]
            if not same_transform(obj, previous) and obj.structural and not body.structural_editing:
                raise HTTPException(422, "Enable structural editing before changing this element.")
            if (
                obj.structural
                and obj.deleted
                and not previous.deleted
                and not body.confirm_structural_deletion
            ):
                raise HTTPException(422, "Confirm structural deletion first.")
        scan.scene = body.scene
        scan.revision += 1
        refresh_counts(scan)
        store.save(scan)
        return scan


def refresh_counts(scan):
    from collections import Counter

    visible = [o for o in scan.scene.objects if not o.deleted]
    scan.stats.objects = len(visible)
    scan.stats.entrances = sum(o.entrance for o in visible)
    counts = Counter(o.kind for o in visible)
    scan.detections = [
        {
            "kind": k,
            "count": v,
            "confidence": sum(o.confidence for o in visible if o.kind == k) / v,
        }
        for k, v in counts.items()
    ]


@router.post("/{scan_id}/reset", response_model=ScanResponse)
def reset(scan_id: UUID, request: Request):
    store = request.app.state.scan_store
    with store.lock:
        scan = require(request, scan_id)
        scene = store.original(scan_id)
        if not scene:
            raise HTTPException(409, "No original scene available.")
        scan.scene = scene
        scan.revision += 1
        refresh_counts(scan)
        store.save(scan)
        return scan


@router.get("/{scan_id}/export")
def export(scan_id: UUID, request: Request):
    scan = require(request, scan_id)
    original = request.app.state.scan_store.original(scan_id)
    if not scan.scene or not original:
        raise HTTPException(409, "No scene available to export.")
    return {"format": "spatial-scene-v2", "scan": scan, "original": original}


@router.get("/{scan_id}/artifacts/{filename}")
def artifact(scan_id: UUID, filename: str, request: Request):
    require(request, scan_id, include_scene=False)
    import re

    if not re.fullmatch(
        r"(frame-\d+\.jpg|segmentation-\d+\.jpg|depth-(refined-)?\d+\.(png|npy)|detection-\d+\.jpg|detections-\d+\.json|mask-\d+\.png|camera-poses\.json|registration\.json|structure-fit\.json|instance-tracks\.json|motion-report\.json|fixture-fit\.json|opening-fit\.json|frame-quality\.json|metrics\.json|model\.(glb|blend)|blender-scene\.json|blender\.log|room-plan\.json|gemini-generation\.json|gemini-review\.json|review-view-[0-2]\.png|frame-selection\.json|cloud\.ply|scene\.json|source\.(mp4|mov|webm|avi|mkv))",
        filename,
    ):
        raise HTTPException(404, "Artifact not found.")
    path = request.app.state.scan_store.directory(scan_id) / filename
    if not path.is_file():
        raise HTTPException(404, "Artifact is not available yet.")
    return FileResponse(path)


@router.post("/{scan_id}/calibration", response_model=ScanResponse)
def calibrate(scan_id: UUID, body: CalibrationEdit, request: Request):
    store = request.app.state.scan_store
    with store.lock:
        scan = require(request, scan_id)
        if scan.scene is None or scan.status not in TERMINAL:
            raise HTTPException(409, "Wait for the reconstruction before scaling.")
        if body.revision != scan.revision:
            raise HTTPException(409, "Scene changed in another session. Reload the saved scan.")
        original = store.original(scan_id)
        try:
            scan.scene = apply_calibration(scan.scene, body.calibration, original)
            validate_edit(original, scan.scene)
        except ValueError as exc:
            raise HTTPException(
                422, "Scale would exceed scene limits. Check the reference."
            ) from exc
        scan.revision += 1
        store.save(scan)
        return scan


@router.patch("/{scan_id}/transforms")
def save_transforms(scan_id: UUID, body: TransformEdits, request: Request):
    """Small transactions retain geometry; calibration can be restored with editor history."""
    store = request.app.state.scan_store
    with store.lock:
        scan = require(request, scan_id)
        if scan.scene is None or scan.status not in TERMINAL:
            raise HTTPException(409, "Wait for the reconstruction before editing.")
        if body.revision != scan.revision:
            raise HTTPException(409, "Scene changed in another session. Reload the saved scan.")
        original = store.original(scan_id)
        if "calibration" in body.model_fields_set:
            try:
                scan.scene = apply_calibration(scan.scene, body.calibration, original)
            except ValueError as exc:
                raise HTTPException(
                    422, "Scale would exceed scene limits. Check the reference."
                ) from exc
        objects = {o.id: o for o in scan.scene.objects}
        for change in body.changes:
            obj = objects.get(change.id)
            if obj is None:
                raise HTTPException(422, "Unknown scene element.")
            if not same_transform(obj, change) and obj.structural and not body.structural_editing:
                raise HTTPException(422, "Enable structural editing before changing this element.")
            if (
                obj.structural
                and change.deleted
                and not obj.deleted
                and not body.confirm_structural_deletion
            ):
                raise HTTPException(422, "Confirm structural deletion first.")
            obj.position = change.position
            obj.rotation = change.rotation
            obj.scale = change.scale
            obj.deleted = change.deleted
        try:
            validate_edit(original, scan.scene)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        scan.revision += 1
        refresh_counts(scan)
        store.save(scan)
        return scan.model_dump(mode="json", exclude={"scene"})
