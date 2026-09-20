"""Queued Blender generation/import using either isolated MCP or headless Python."""

import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from app.schemas import ModelAsset, Scene, SceneObject
from app.services.video import ProcessingError

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "blender"


def run_process(command, output, timeout, check, env=None):
    with output.open("ab") as log:
        proc = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True
        )
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                check()
                if time.monotonic() > deadline:
                    raise ProcessingError(
                        "Blender timed out. Try a simpler scene or increase the worker timeout."
                    )
                time.sleep(0.15)
            if proc.returncode:
                raise ProcessingError(
                    "Blender could not build/export this model. See blender.log in diagnostics."
                )
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()


def load_scene(output):
    try:
        raw = (output / "model.glb").read_bytes()
        details = json.loads((output / "blender-scene.json").read_text())
        asset = ModelAsset(
            data=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest()
        )
        scene = Scene(
            asset=asset,
            preview_direction=details.get("preview_direction"),
            objects=[SceneObject.model_validate(o) for o in details["objects"]],
            scale_note=details["scale_note"],
            unobserved=details["unobserved"],
        )
        return scene, raw, details
    except (OSError, ValueError, KeyError) as exc:
        raise ProcessingError(
            "Blender output did not pass scene validation. Inspect blender.log."
        ) from exc


class BlenderService:
    def __init__(self, settings):
        self.settings = settings

    def available(self):
        if self.settings.blender_transport == "container":
            from app.services.container_worker import worker_available

            return worker_available(self.settings.blender_jobs_dir)
        return bool(shutil.which(self.settings.blender_binary)) and (
            self.settings.blender_transport == "headless"
            or bool(shutil.which(self.settings.blender_mcp_command))
        )

    def executable(self):
        if self.settings.blender_transport == "container":
            if not self.available():
                raise ProcessingError("The Docker Blender worker is offline. Start the worker.")
            return "container"
        binary = shutil.which(self.settings.blender_binary)
        if not binary:
            raise ProcessingError(
                "Blender is not configured. Set SPATIAL_BLENDER_BINARY to the Blender executable."
            )
        return binary

    def reconstruct(self, path, scan, output, update, check):
        self.executable()
        config = self.settings
        is_video = path.suffix.lower() not in {".blend", ".glb", ".json"}
        generated = is_video and config.blender_provider == "gemini"
        if generated:
            from app.services.gemini import generate

            failure = ""
            for attempt in range(2):
                try:
                    if attempt == 0:
                        source = generate(path, scan, output, config, update, check)
                    else:
                        previous = (output / "gemini-scene.py").read_text()
                        (output / "gemini-scene-attempt-1.py").write_text(previous)
                        update(
                            stage="repairing",
                            message="Gemini is correcting Blender compatibility",
                            progress=40,
                        )
                        source = generate(
                            path,
                            scan,
                            output,
                            config,
                            update,
                            check,
                            previous=previous,
                            failure=failure,
                        )
                    self.execute(source, output, update, check)
                    break
                except ProcessingError as exc:
                    if attempt or not (output / "gemini-scene.py").exists():
                        raise
                    failure = str(exc)
                    log = output / "blender.log"
                    if log.exists():
                        failure += "\n" + log.read_text(errors="replace")[-6000:]
                    for name in (
                        "model.glb",
                        "model.blend",
                        "blender-scene.json",
                        "generated.blend",
                    ):
                        (output / name).unlink(missing_ok=True)
        else:
            if is_video:
                from app.services.room_plan import plan_video

                update(
                    stage="planning",
                    message="Selecting views and interpreting the room",
                    progress=5,
                )
                plan = plan_video(path, scan, output, config, update, check)
                source = output / "room-plan.json"
                source.write_text(plan.model_dump_json(indent=2))
            else:
                source = path
            if source.suffix == ".json":
                from app.services.room_plan import RoomPlan

                try:
                    plan = RoomPlan.model_validate_json(source.read_text())
                    source.write_text(plan.model_dump_json())
                except ValueError as exc:
                    raise ProcessingError(
                        "Invalid room plan: dimensions, openings or objects are inconsistent."
                    ) from exc
            self.execute(source, output, update, check)
        check()
        if generated and config.blender_visual_review:
            from app.services.visual_review import improve

            improve(self, path, scan, output, update, check)
        update(stage="validating", message="Checking model geometry and materials", progress=90)
        scan.scene, raw, details = load_scene(output)
        from collections import Counter

        kinds = Counter(o.kind for o in scan.scene.objects)
        scan.detections = [
            dict(kind=k, count=n, confidence=0.7 if generated else 1) for k, n in kinds.items()
        ]
        scan.stats.objects = len(scan.scene.objects)
        scan.stats.entrances = sum(o.entrance for o in scan.scene.objects)
        scan.stats.vertices = sum(len(o.geometry.vertices) for o in scan.scene.objects)
        scan.stats.artifact_bytes = len(raw)
        scan.stats.execution_device = "Blender / " + config.blender_transport
        scan.warnings = [
            "Blender model: layout and dimensions are estimates; inspect against the source "
            "before navigation.",
            "Door geometry does not establish a verified entrance or exit.",
        ] + details.get("warnings", [])
        scan.artifact_type = "Blender GLB + semantic mesh JSON"
        scan.status = "degraded"
        update(stage="finished", message="Blender model ready in the Sandbox", progress=100)
        return scan

    def execute(self, source, output, update, check):
        config = self.settings
        binary = self.executable()
        update(stage="blender", message="Building the Blender model", progress=45)
        if source.suffix == ".py":
            function, filename = "build_generated", "generated_build.py"
        elif source.suffix == ".json":
            function, filename = "build_and_export", "build_scene.py"
        else:
            function, filename = "export_room", "export_scene.py"
        if config.blender_transport == "container":
            from app.services.container_worker import execute_container

            execute_container(source, output, config, check)
            return
        script = SCRIPTS / filename
        worker_binary = binary
        env = None
        if source.suffix == ".py":
            from app.services.generated_code import isolated_binary, worker_environment

            worker_binary = isolated_binary(binary, output, SCRIPTS)
            env = worker_environment(output)
        code = (
            f"import runpy\nresult = runpy.run_path({str(script)!r})"
            f"[{function!r}]({str(source)!r}, {str(output)!r})\n"
        )
        log = output / "blender.log"
        if config.blender_transport == "mcp":
            command = shutil.which(config.blender_mcp_command)
            if not command:
                raise ProcessingError(
                    "Blender MCP server is not configured. Set SPATIAL_BLENDER_MCP_COMMAND."
                )
            # Owned seed avoids reading or overwriting an interactive Blender session.
            seed = output / "seed.blend"
            run_process(
                [
                    binary,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--python-exit-code",
                    "1",
                    "--python-expr",
                    f"import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(seed)!r})",
                ],
                log,
                config.blender_timeout_seconds,
                check,
            )
            request = output / "mcp-request.json"
            request.write_text(
                json.dumps(
                    dict(
                        command=command,
                        binary=worker_binary,
                        seed=str(seed),
                        code=code,
                        timeout=config.blender_timeout_seconds,
                        receipt=str(output / "mcp-receipt.json"),
                    )
                )
            )
            run_process(
                [config.blender_mcp_python, str(SCRIPTS / "mcp_execute.py"), str(request)],
                log,
                config.blender_timeout_seconds,
                check,
                env=env,
            )
        else:
            run_process(
                [
                    worker_binary,
                    "--background",
                    "--factory-startup",
                    "--disable-autoexec",
                    "--python-exit-code",
                    "1",
                    "--python-expr",
                    code,
                ],
                log,
                config.blender_timeout_seconds,
                check,
                env=env,
            )
