"""Transfer one Blender job to a secret-free, network-disabled container via a volume.

Only the current job is staged here; persistent scans and credentials are never mounted
in the worker. Run one API process and one worker per deployment.
"""

import json
import shutil
import time
from pathlib import Path
from uuid import uuid4

from app.services.video import ProcessingError

OUTPUTS = {
    "model.glb": 16 * 1024**2,
    "blender-scene.json": 64 * 1024**2,
    "model.blend": 256 * 1024**2,
    "generated.blend": 256 * 1024**2,
    "blender.log": 8 * 1024**2,
}


def worker_available(root):
    try:
        return 0 <= time.time() - (Path(root) / "heartbeat").stat().st_mtime < 15
    except OSError:
        return False


def execute_container(source, output, settings, check):
    root = settings.blender_jobs_dir
    if not worker_available(root):
        raise ProcessingError("The Docker Blender worker is offline. Start the worker.")
    job = root / uuid4().hex
    job.mkdir(mode=0o700)
    completed = False
    try:
        shutil.copyfile(source, job / ("source" + source.suffix.lower()))
        if source.suffix == ".py":
            shutil.copyfile(output / "gemini-generation.json", job / "gemini-generation.json")
        payload = {"suffix": source.suffix.lower(), "timeout": settings.blender_timeout_seconds}
        (job / "request.tmp").write_text(json.dumps(payload))
        (job / "request.tmp").replace(job / "request.json")
        deadline = time.monotonic() + settings.blender_timeout_seconds + 15
        while not (job / "result.json").is_file():
            check()
            if time.monotonic() > deadline:
                raise ProcessingError("Docker Blender worker timed out. Check worker logs.")
            if not worker_available(root):
                raise ProcessingError("Docker Blender worker stopped during the build.")
            time.sleep(0.15)
        completed = True
        result_file = job / "result.json"
        if result_file.is_symlink() or result_file.stat().st_size > 4096:
            raise ProcessingError("Invalid Docker worker receipt.")
        result = json.loads(result_file.read_text())
        for name, limit in OUTPUTS.items():
            artifact = job / name
            if artifact.exists():
                if (
                    artifact.is_symlink()
                    or not artifact.is_file()
                    or artifact.stat().st_size > limit
                ):
                    raise ProcessingError("Docker worker output exceeds the artifact limits.")
                shutil.copyfile(artifact, output / name)
        if result.get("status") != "ok":
            raise ProcessingError("Blender could not build/export this model. See blender.log.")
        if not all((output / name).is_file() for name in ("model.glb", "blender-scene.json")):
            raise ProcessingError("Docker worker did not produce a complete scene.")
    finally:
        if not completed:
            (job / "cancel").touch(exist_ok=True)
            # Wait for process-group termination before allowing another job to start.
            stop_deadline = time.monotonic() + 6
            while worker_available(root) and time.monotonic() < stop_deadline:
                if (job / "result.json").exists():
                    completed = True
                    break
                time.sleep(0.1)
        if completed:
            shutil.rmtree(job, ignore_errors=True)
        # An offline worker consumes cancellation and cleans the orphan when it restarts.
