"""Preflight checks plus an OS sandbox for model-authored Blender geometry."""

import ast
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from app.services.video import ProcessingError


def validate_code(code):
    if len(code) > 150_000:
        raise ProcessingError("Generated Blender script exceeds the code budget.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ProcessingError(
            f"Generated Blender script has a syntax error at line {exc.lineno}."
        ) from None
    forbidden = {
        "exec",
        "eval",
        "compile",
        "open",
        "input",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "memoryview",
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            if any(name not in {"bpy", "math", "mathutils", "random"} for name in names):
                raise ProcessingError("Generated code requested an unsupported import.")
        if isinstance(node, ast.Name) and (node.id in forbidden or node.id.startswith("__")):
            raise ProcessingError("Generated code requested an unsupported Python operation.")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__")
            or node.attr
            in {
                "driver_add",
                "handlers",
                "load",
                "libraries",
                "texts",
                "exec",
                "system",
                "popen",
                "register_class",
                "user_preferences",
                "preferences",
                "script",
                "python_file_run",
                "open_mainfile",
                "save_as_mainfile",
                "save_mainfile",
                "export_scene",
                "import_scene",
            }
        ):
            raise ProcessingError("Generated code requested file access or executable scene hooks.")
    if "bpy" not in code:
        raise ProcessingError("Generated script does not construct Blender geometry.")


def worker_environment(output):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    runtime = output / "runtime"
    runtime.mkdir(exist_ok=True)
    env.update(
        TMPDIR=str(runtime),
        PYTHONDONTWRITEBYTECODE="1",
        BLENDER_USER_CONFIG=str(runtime / "config"),
        BLENDER_USER_SCRIPTS=str(runtime / "scripts"),
        BLENDER_USER_DATAFILES=str(runtime / "datafiles"),
    )
    return env


def isolated_binary(binary, output, scripts):
    """MCP receives this wrapper so only its Blender child executes model-authored code."""
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        raise ProcessingError(
            "Gemini code generation currently requires the macOS isolated Blender "
            "worker. Configure a container-isolated worker before deploying elsewhere."
        )
    output = output.resolve()
    scripts = scripts.resolve()
    allowed = [output, scripts, Path(binary).resolve().parents[2]]
    reads = "\n".join("(allow file-read* (subpath " + json.dumps(str(p)) + "))" for p in allowed)
    profile = output / "worker.sb"
    profile.write_text(
        "(version 1)\n(allow default)\n(deny network*)\n"
        "(deny process-exec)\n(allow process-exec (literal "
        + json.dumps(str(Path(binary).resolve()))
        + "))\n"
        "(deny file-write*)\n(allow file-write* (subpath " + json.dumps(str(output)) + "))\n"
        '(allow file-write* (literal "/dev/null"))\n'
        "(deny file-read* (subpath " + json.dumps(str(Path.home())) + "))\n" + reads + "\n"
    )
    wrapper = output / "blender-worker"
    wrapper.write_text(
        "#!/bin/sh\nexec /usr/bin/sandbox-exec -f "
        + shlex.quote(str(profile))
        + " "
        + shlex.quote(binary)
        + ' --disable-autoexec "$@"\n'
    )
    wrapper.chmod(0o700)
    return str(wrapper)
