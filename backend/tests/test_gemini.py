"""Gemini contracts are mocked; no credentials or network are used by these tests."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import gemini
from app.services.generated_code import isolated_binary, validate_code, worker_environment
from app.services.video import Cancelled, ProcessingError


def settings(**kw):
    return Settings(
        _env_file=None, blender_provider="gemini", blender_planner_model="gemini-3.6-flash", **kw
    )


def test_credentials_environment_priority_and_hidden_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    assert gemini.load_key(settings()) == "test-gemini-key"
    config = settings(blender_api_key="test-explicit-key")
    assert gemini.load_key(config) == "test-explicit-key"
    assert "test-explicit-key" not in repr(config)


def test_exact_keychain_service_and_no_key_persistence(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gemini.sys, "platform", "darwin")
    seen = []

    def lookup(command, **kwargs):
        seen.append(command)
        assert kwargs["capture_output"] and kwargs["timeout"] == 10
        return SimpleNamespace(returncode=0, stdout="test-keychain-key\n")

    monkeypatch.setattr(gemini.subprocess, "run", lookup)
    assert (
        gemini.load_key(settings(gemini_keychain_service="vt-hacks-gemini-api"))
        == "test-keychain-key"
    )
    assert seen == [["security", "find-generic-password", "-s", "vt-hacks-gemini-api", "-w"]]


@pytest.mark.parametrize(
    "code",
    [
        "import os\nimport bpy",
        'import bpy\nopen("secret")',
        'import bpy\neval("1")',
        'import bpy\nbpy.data.texts.new("script")',
        'import bpy\nbpy.ops.wm.open_mainfile(filepath="secret")',
        'import bpy\nbpy.context.object.driver_add("location")',
        "import bpy\n().__class__",
    ],
)
def test_generated_code_rejects_non_geometry_operations(code):
    with pytest.raises(ProcessingError):
        validate_code(code)


def test_environment_does_not_pass_api_keys_to_blender(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")
    monkeypatch.setenv("SPATIAL_BLENDER_API_KEY", "another-test-secret")
    env = worker_environment(tmp_path)
    assert "GEMINI_API_KEY" not in env and "SPATIAL_BLENDER_API_KEY" not in env
    assert env["TMPDIR"] == str(tmp_path / "runtime")


def test_generated_script_metadata_and_frame_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test-key")
    monkeypatch.setattr(gemini, "select_frames", lambda *args: [10, 20])
    for frame in [10, 20]:
        (tmp_path / f"frame-{frame:06}.jpg").write_bytes(b"fixture image")
    code = "import bpy\nbpy.ops.mesh.primitive_cube_add()\n"
    captured = []

    async def response(key, config, parts, check):
        captured.extend(parts)
        return SimpleNamespace(
            function_calls=[
                SimpleNamespace(
                    name=gemini.FUNCTION,
                    args={
                        "code": code,
                        "summary": "Furnished room",
                        "assumptions": ["Dimensions estimated"],
                    },
                )
            ]
        )

    monkeypatch.setattr(gemini, "request_scene", response)
    generated = gemini.generate(
        tmp_path / "input.mov", None, tmp_path, settings(), lambda **kw: None, lambda: None
    )
    assert generated.read_text().strip() == code.strip()
    metadata = json.loads((tmp_path / "gemini-generation.json").read_text())
    assert metadata["model"] == "gemini-3.6-flash"
    assert metadata["source_frames"] == [10, 20]
    assert len([part for part in captured if part.inline_data]) == 2
    assert "test-key" not in (tmp_path / "gemini-generation.json").read_text()


def test_sdk_errors_do_not_expose_key_or_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test-private-key")
    monkeypatch.setattr(gemini, "select_frames", lambda *args: [])

    async def fail(*args):
        raise RuntimeError("test-private-key private frame prompt")

    monkeypatch.setattr(gemini, "request_scene", fail)
    with pytest.raises(ProcessingError) as error:
        gemini.generate(
            tmp_path / "x.mov", None, tmp_path, settings(), lambda **kw: None, lambda: None
        )
    assert "test-private-key" not in str(error.value)
    assert "private frame" not in str(error.value)


def test_cancellation_does_not_become_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test-key")
    monkeypatch.setattr(gemini, "select_frames", lambda *args: [])

    async def cancelled(*args):
        raise Cancelled("cancelled")

    monkeypatch.setattr(gemini, "request_scene", cancelled)
    with pytest.raises(Cancelled):
        gemini.generate(
            tmp_path / "x.mov", None, tmp_path, settings(), lambda **kw: None, lambda: None
        )


def test_isolation_profile_blocks_network_other_home_and_outside_writes(tmp_path, monkeypatch):
    import app.services.generated_code as policy

    monkeypatch.setattr(policy.sys, "platform", "darwin")
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/sandbox-exec")
    binary = "/Applications/Blender.app/Contents/MacOS/Blender"
    wrapper = Path(isolated_binary(binary, tmp_path, tmp_path / "scripts"))
    assert "--disable-autoexec" in wrapper.read_text()
    profile = (tmp_path / "worker.sb").read_text()
    assert "(deny network*)" in profile and "(deny file-write*)" in profile
    assert "(deny process-exec)" in profile and str(Path.home()) in profile


def test_high_demand_has_actionable_error_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test-key")
    monkeypatch.setattr(gemini, "select_frames", lambda *args: [])

    class Busy(Exception):
        code = 503

    async def busy(*args):
        raise Busy("private request payload")

    monkeypatch.setattr(gemini, "request_scene", busy)
    with pytest.raises(ProcessingError, match="high demand"):
        gemini.generate(
            tmp_path / "x.mov", None, tmp_path, settings(), lambda **kw: None, lambda: None
        )
    assert json.loads((tmp_path / "gemini-error.json").read_text())["status"] == 503


@pytest.mark.parametrize("second_pass_fails", [False, True])
def test_selected_frames_never_seek_and_keep_valid_fallback(
    tmp_path, monkeypatch, second_pass_fails
):
    import cv2
    import numpy as np

    frame = np.full((20, 30, 3), 100, dtype=np.uint8)
    for index in (0, 2):
        assert cv2.imwrite(str(tmp_path / f"frame-{index:06}.jpg"), frame)
    monkeypatch.setattr(gemini, "extract", lambda *a: ([(0, frame), (2, frame)], [], 3))

    class Capture:
        index = 0

        def set(self, *a):
            pytest.fail("Frame seeking must never be used")

        def read(self):
            self.index += 1
            return (True, frame) if not second_pass_fails and self.index <= 3 else (False, None)

        def release(self):
            pass

    monkeypatch.setattr(gemini.cv2, "VideoCapture", lambda *a: Capture())
    selected = gemini.select_frames(
        tmp_path / "camera.webm",
        SimpleNamespace(video=None),
        tmp_path,
        lambda **k: None,
        lambda: None,
    )
    assert selected == [0, 2]
    report = json.loads((tmp_path / "frame-selection.json").read_text())
    assert report["fallback_frames"] == ([0, 2] if second_pass_fails else [])
    assert all(cv2.imread(str(tmp_path / f"frame-{i:06}.jpg")) is not None for i in selected)


@pytest.mark.parametrize("cancel", [False, True])
def test_real_sdk_request_lifetime_and_cancellation(monkeypatch, cancel):
    """Exercise the installed SDK; mock only HTTP, not generate_content."""
    import asyncio
    import gc

    import httpx

    closed = []
    entered = []
    finished = []

    async def respond(request):
        gc.collect()
        entered.append(True)
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "gemini-3.6-flash:generateContent" in str(request.url)
        payload = json.loads(request.content)
        assert payload["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
        try:
            if cancel:
                await asyncio.sleep(30)
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": gemini.FUNCTION,
                                            "args": {
                                                "code": "import bpy",
                                                "summary": "Probe",
                                                "assumptions": [],
                                            },
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        finally:
            finished.append(True)

    class Transport(httpx.MockTransport):
        async def aclose(self):
            closed.append(True)
            await super().aclose()

    real_client = gemini.genai.Client

    def client(**kwargs):
        kwargs["http_options"].async_client_args = {"transport": Transport(respond)}
        return real_client(**kwargs)

    monkeypatch.setattr(gemini.genai, "Client", client)

    def check():
        if cancel and entered:
            raise Cancelled("cancelled")

    async def run():
        try:
            result = await gemini.request_scene(
                "test-key", settings(), [gemini.types.Part.from_text(text="Probe")], check
            )
            assert not cancel
            assert result.function_calls[0].name == gemini.FUNCTION
        finally:
            assert finished, "The HTTP request must finish or be cancelled before returning"

    if cancel:
        with pytest.raises(Cancelled):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert entered and closed
