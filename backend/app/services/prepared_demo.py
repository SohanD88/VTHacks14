"""Load the reviewed demo directly or stage a matched video upload for the demo."""

import base64
import gzip
import json
import shutil
import time
from collections import Counter
from pathlib import Path

from app.schemas import Scene
from app.services.video import ProcessingError

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo_assets" / "virginia-lounge"
DEMO_NAME = "Prepared demo · Virginia lounge · IMG_1343"


def matches_demo(digest):
    """Match the original file contents, never an arbitrary video's filename."""
    reference = DEMO_DIR / "source.json"
    return reference.is_file() and digest == json.loads(reference.read_text())["sha256"]


def read_bundle():
    bundle = DEMO_DIR / "scene.json.gz"
    if not bundle.is_file():
        raise ProcessingError("The prepared lounge demo has not been built on this server.")
    return json.loads(gzip.decompress(bundle.read_bytes()))


def populate(scan, scene, warnings, directory):
    raw = base64.b64decode(scene.asset.data, validate=True)
    scan.processing_mode = "blender"
    scan.scene = scene
    scan.warnings = list(warnings)
    scan.artifact_type = "Prepared Blender demo · GLB + semantic geometry"
    scan.stats.objects = len(scene.objects)
    scan.stats.entrances = sum(o.entrance for o in scene.objects)
    scan.stats.vertices = sum(len(o.geometry.vertices) for o in scene.objects)
    scan.stats.artifact_bytes = len(raw)
    scan.stats.execution_device = "Prepared local artifact (no model call)"
    scan.detections = [
        dict(kind=k, count=n, confidence=0.8)
        for k, n in Counter(o.kind for o in scene.objects).items()
    ]
    (directory / "model.glb").write_bytes(raw)
    blend = DEMO_DIR / "model.blend"
    if blend.exists():
        shutil.copyfile(blend, directory / "model.blend")


def load_prepared_demo(store):
    data = read_bundle()
    scene = Scene.model_validate(data["scene"])
    # Reopen an unedited copy of this exact model version.
    with store.lock:
        for existing in store.scans.values():
            if (
                existing.name == DEMO_NAME
                and existing.source == "import"
                and existing.stage == "finished"
                and existing.revision == 0
            ):
                saved = store.get(existing.id)
                if (
                    saved
                    and saved.scene
                    and saved.scene.asset
                    and saved.scene.asset.sha256 == scene.asset.sha256
                ):
                    return saved
        serialized = scene.model_dump_json()
        blend = DEMO_DIR / "model.blend"
        required = (
            len(serialized.encode()) * 2
            + len(scene.asset.data)
            + (blend.stat().st_size if blend.exists() else 0)
        )
        scan = store.reserve(required)
        directory = store.directory(scan.id)
        try:
            scan.name = DEMO_NAME
            scan.source = "import"
            populate(scan, scene, data["warnings"], directory)
            scan.status = "degraded"
            scan.stage = "finished"
            scan.progress = 100
            scan.message = "Prepared video-guided demo loaded; no reconstruction wait."
            store.atomic(directory / "original.json", serialized)
            store.save(scan)
            return scan
        except Exception:
            scan.status = "failed"
            scan.message = "Prepared demo could not be loaded."
            store.save(scan)
            raise


class PreparedVideoService:
    """User-requested ten-second presentation pacing for an exact reference match.

    These are prepared-model loading steps, not simulated AI reconstruction stages.
    Cancellation remains available throughout the paced sequence.
    """

    initial_stage = "demo_reference"
    initial_message = "Demo video recognized · loading the prepared model"

    def wait_until(self, deadline, check):
        while (remaining := deadline - time.monotonic()) > 0:
            check()
            time.sleep(min(0.05, remaining))
        check()

    def reconstruct(self, path, scan, output, update, check):
        started = time.monotonic()
        update(
            stage="demo_reference",
            progress=10,
            message="Demo video recognized · loading the prepared model",
        )
        data = read_bundle()
        self.wait_until(started + 2, check)
        update(
            stage="demo_geometry",
            progress=30,
            message="Prepared demo · checking floors, walls, and cross-passage geometry",
        )
        scene = Scene.model_validate(data["scene"])
        self.wait_until(started + 4, check)
        update(
            stage="demo_details",
            progress=55,
            message="Prepared demo · checking furnishings and entrance/exit objects",
        )
        if not scene.asset or not any(o.entrance for o in scene.objects):
            raise ProcessingError("Prepared demo is missing its model or door metadata.")
        self.wait_until(started + 6, check)
        update(
            stage="demo_assets",
            progress=75,
            message="Prepared demo · loading Blender materials and editable objects",
        )
        populate(scan, scene, data["warnings"], output)
        scan.warnings.append(
            "Source video matched by file contents; this loads the prepared demo model."
        )
        self.wait_until(started + 8, check)
        update(stage="demo_ready", progress=90, message="Prepared demo · preparing the Sandbox")
        self.wait_until(started + 10, check)
        scan.status = "degraded"
        update(stage="finished", progress=100, message="Prepared demo ready in the Sandbox")
        return scan
