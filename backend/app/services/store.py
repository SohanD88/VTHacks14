"""Single-process persistent jobs, atomic scene writes and bounded local storage."""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock
from time import perf_counter
from uuid import UUID, uuid4

from app.schemas import ScanResponse, Scene
from app.services.video import Cancelled, ProcessingError

logger = logging.getLogger("spatial.jobs")
TERMINAL = {"completed", "degraded", "failed", "cancelled"}


class ScanStore:
    def __init__(self, root: Path, capacity=20, max_bytes=2 * 1024**3):
        self.root = root
        self.capacity = capacity
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.scans = {}
        self.cancellation = {}
        self.reserved_bytes = {}
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconstruction")
        for path in sorted(root.glob("*/job.json")):
            try:
                scan = ScanResponse.model_validate_json(path.read_text())
                if scan.status not in TERMINAL:
                    scan.status = "failed"
                    scan.error = "Backend restarted during processing. Submit the video again."
                    scan.message = scan.error
                self.scans[str(scan.id)] = scan.model_copy(update={"scene": None}).model_copy(
                    deep=True
                )
                self.save(scan)
            except (ValueError, OSError):
                logger.exception("Could not recover saved scan")

    def directory(self, id):
        return self.root / str(UUID(str(id)))

    def atomic(self, path, data):
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(data)
        temp.replace(path)

    def save(self, scan):
        with self.lock:
            self.scans[str(scan.id)] = scan.model_copy(update={"scene": None}).model_copy(deep=True)
            if scan.status in TERMINAL:
                self.reserved_bytes.pop(str(scan.id), None)
            directory = self.directory(scan.id)
            directory.mkdir(exist_ok=True)
            self.atomic(directory / "job.json", scan.model_dump_json())

    def reserve(self, required_bytes=0):
        with self.lock:
            if sum(s.status not in TERMINAL for s in self.scans.values()) >= 3:
                raise ProcessingError("Processing queue is full. Wait for a job or cancel one.")
            total = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
            if total + required_bytes + sum(self.reserved_bytes.values()) >= self.max_bytes:
                raise ProcessingError(
                    "Local storage limit reached. Delete older scans before uploading."
                )
            if len(self.scans) >= self.capacity:
                raise ProcessingError("Scan limit reached. Delete an older scan before uploading.")
            id = uuid4()
            scan = ScanResponse(id=id, name="Uploading", stage="uploading")
            self.save(scan)
            self.reserved_bytes[str(id)] = required_bytes
            return scan

    def get(self, id, include_scene=True):
        with self.lock:
            scan = self.scans.get(str(id))
            if not scan:
                return None
            if not include_scene:
                return scan.model_copy(deep=True)
            path = self.directory(id) / "job.json"
        try:
            return ScanResponse.model_validate_json(path.read_text())
        except FileNotFoundError:
            return None

    def submit(self, scan, path, service):
        event = Event()
        self.cancellation[str(scan.id)] = event
        self.save(scan)

        def check():
            if event.is_set():
                raise Cancelled()

        started = perf_counter()

        def update(**patch):
            check()
            patch["processing_ms"] = round((perf_counter() - started) * 1000)
            with self.lock:
                for key, value in patch.items():
                    if key in type(scan.stats).model_fields:
                        setattr(scan.stats, key, value)
                    else:
                        setattr(scan, key, value)
                # Persist stage changes and measured counters; no elapsed-time simulation.
                self.save(scan)

        def run():
            try:
                check()
                scan.status = "processing"
                update(
                    stage=getattr(service, "initial_stage", "decoding"),
                    message=getattr(service, "initial_message", "Reading video frames"),
                )
                result = service.reconstruct(path, scan, self.directory(scan.id), update, check)
                check()
                self.atomic(
                    self.directory(scan.id) / "original.json", result.scene.model_dump_json()
                )
                path.rename(path.with_name("source" + path.suffix))
                self.save(result)
            except Cancelled:
                scan.status = "cancelled"
                scan.message = "Processing cancelled. Submit the video again to retry."
                scan.stage = "cancelled"
                self.save(scan)
            except ProcessingError as exc:
                scan.status = "failed"
                scan.error = str(exc)
                scan.message = str(exc)
                self.save(scan)
            except (MemoryError, RuntimeError):
                logger.exception("Reconstruction resource failure")
                scan.status = "failed"
                scan.error = (
                    "Processing ran out of resources or a model failed. Try quick mode"
                    " and close other GPU applications."
                )
                scan.message = scan.error
                self.save(scan)
            except Exception:
                logger.exception("Unexpected reconstruction failure")
                scan.status = "failed"
                scan.error = (
                    "Reconstruction failed unexpectedly. Check backend logs and retry "
                    "with a shorter H.264 recording."
                )
                scan.message = scan.error
                self.save(scan)
            finally:
                path.unlink(missing_ok=True)
                self.cancellation.pop(str(scan.id), None)

        self.worker.submit(run)

    def cancel(self, id):
        with self.lock:
            event = self.cancellation.get(str(id))
            if event:
                event.set()
            return bool(event)

    def original(self, id):
        path = self.directory(id) / "original.json"
        return Scene.model_validate_json(path.read_text()) if path.exists() else None

    def delete(self, id):
        with self.lock:
            if self.scans[str(id)].status not in TERMINAL:
                raise ProcessingError(
                    "Cancel processing and wait for cancellation before deleting."
                )
            shutil.rmtree(self.directory(id))
            self.scans.pop(str(id), None)

    def close(self):
        for event in list(self.cancellation.values()):
            event.set()
        self.worker.shutdown(wait=True, cancel_futures=False)
