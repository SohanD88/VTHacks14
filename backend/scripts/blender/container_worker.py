"""Single-job worker. Deploy only using the network-disabled worker service in compose.yaml."""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path("/jobs")
SCRIPTS = Path(__file__).resolve().parent
BUILDERS = {
    ".py": ("generated_build.py", "build_generated"),
    ".json": ("build_scene.py", "build_and_export"),
    ".blend": ("export_scene.py", "export_room"),
    ".glb": ("export_scene.py", "export_room"),
}


def heartbeat():
    (ROOT / "heartbeat").touch()


def perform(job):
    if (job / "cancel").exists():
        shutil.rmtree(job, ignore_errors=True)
        return
    status = "error"
    try:
        request = json.loads((job / "request.json").read_text())
        suffix = request["suffix"]
        filename, function = BUILDERS[suffix]
        timeout = min(1800, max(10, int(request["timeout"])))
        code = (
            f"import runpy; runpy.run_path({str(SCRIPTS / filename)!r})"
            f"[{function!r}]({str(job / ('source' + suffix))!r}, {str(job)!r})"
        )
        runtime = job / "runtime"
        runtime.mkdir(exist_ok=True)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(runtime),
            "TMPDIR": str(runtime),
            "LANG": "C.UTF-8",
            "BLENDER_USER_CONFIG": str(runtime / "config"),
            "BLENDER_USER_SCRIPTS": str(runtime / "scripts"),
            "BLENDER_USER_DATAFILES": str(runtime / "datafiles"),
            "OMP_NUM_THREADS": "2",
        }
        with (job / "blender.log").open("wb") as log:
            proc = subprocess.Popen(
                [
                    "blender",
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--threads",
                    "2",
                    "--python-exit-code",
                    "1",
                    "--python-expr",
                    code,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            try:
                while proc.poll() is None:
                    heartbeat()
                    if (
                        (job / "cancel").exists()
                        or time.monotonic() > deadline
                        or log.tell() > 8 * 1024**2
                    ):
                        break
                    time.sleep(0.15)
                if proc.poll() == 0:
                    status = "ok"
            finally:
                # Kill any remaining descendants as well as the direct Blender process.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    except Exception as exc:
        print(f"Worker job failed: {type(exc).__name__}", flush=True)
    finally:
        (job / "result.tmp").write_text(json.dumps({"status": status}))
        (job / "result.tmp").replace(job / "result.json")


def main():
    ROOT.mkdir(exist_ok=True)
    while True:
        heartbeat()
        for job in sorted(ROOT.iterdir()):
            if not job.is_dir() or job.is_symlink() or len(job.name) != 32:
                continue
            if (job / "result.json").exists():
                # Reclaim abandoned results after API/container restart.
                if time.time() - (job / "result.json").stat().st_mtime > 3600:
                    shutil.rmtree(job, ignore_errors=True)
                continue
            if (job / "request.json").is_file():
                perform(job)
        time.sleep(0.2)


if __name__ == "__main__":
    main()
