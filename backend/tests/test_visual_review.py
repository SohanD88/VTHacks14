"""Review selection/rollback and export grouping regressions without paid API calls."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_blender import sample_scene

from app.services import gemini, visual_review
from app.services.blender import load_scene
from app.services.video import Cancelled, ProcessingError

partition = runpy.run_path(str(Path(__file__).parents[1] / "scripts/blender/export_groups.py"))[
    "partition_group"
]


def part(kind, hidden=False, frames=None):
    return dict(kind=kind, hidden=hidden, frames=frames or [1], id=None)


def test_wall_visibility_and_door_accessories_are_not_last_child_wins():
    buckets = partition([part("wall"), part("wall", True), part("wall", frames=[2])])
    assert {(b["kind"], b["hidden"]) for b in buckets} == {("wall", False), ("wall", True)}
    assert next(b for b in buckets if not b["hidden"])["frames"] == [1, 2]
    for parts in (
        [part("door"), part("fixture"), part("windowpane")],
        [part("fixture"), part("windowpane"), part("door")],
    ):
        assert partition(parts)[0]["kind"] == "door"
    assert partition([part("elevator"), part("door"), part("fixture")])[0]["kind"] == "elevator"
    assert {b["kind"] for b in partition([part("wall"), part("floor"), part("ceiling")])} == {
        "wall",
        "floor",
        "ceiling",
    }


def write_scene(output, tag):
    import base64

    scene = sample_scene()
    (output / "model.glb").write_bytes(base64.b64decode(scene.asset.data))
    details = dict(
        objects=[o.model_dump(mode="json") for o in scene.objects],
        scale_note=tag,
        unobserved="Unknown",
        warnings=[],
    )
    (output / "blender-scene.json").write_text(json.dumps(details))
    for index in range(3):
        (output / f"review-view-{index}.png").write_bytes(b"test render")


@pytest.fixture
def baseline(tmp_path):
    write_scene(tmp_path, "baseline")
    (tmp_path / "gemini-generation.json").write_text(json.dumps({"source_frames": [1]}))
    (tmp_path / "gemini-scene.py").write_text("import bpy")
    (tmp_path / "frame-000001.jpg").write_bytes(b"test frame")
    return tmp_path


def assessment(score, correction=True):
    return dict(
        score=score,
        needs_correction=correction,
        summary="Review summary",
        issues=[dict(description="Missing shelf", source_frames=[1])] if correction else [],
    )


@pytest.mark.parametrize("score,expected", [(80, "candidate"), (30, "baseline"), (40, "baseline")])
def test_only_valid_visually_improved_candidate_replaces_baseline(
    baseline, monkeypatch, score, expected
):
    reviews = iter([assessment(40), assessment(score)])
    monkeypatch.setattr(gemini, "review", lambda *a: next(reviews))
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: a[2] / "gemini-scene.py")

    def execute(source, output, *args):
        write_scene(output, "candidate")

    service = SimpleNamespace(settings=SimpleNamespace(), execute=execute)
    result = visual_review.improve(
        service, Path("source.mov"), None, baseline, lambda **k: None, lambda: None
    )
    scene, _, _ = load_scene(baseline)
    assert scene.scale_note == expected
    assert result["corrected"] == (expected == "candidate")
    assert (baseline / "gemini-review.json").exists()


@pytest.mark.parametrize("failure", ["build", "review", "invalid"])
def test_failed_correction_keeps_original(baseline, monkeypatch, failure):
    calls = 0

    def review(*a):
        nonlocal calls
        calls += 1
        if calls > 1 and failure == "review":
            raise ProcessingError("Provider unavailable")
        return assessment(40)

    monkeypatch.setattr(gemini, "review", review)
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: a[2] / "gemini-scene.py")

    def execute(source, output, *args):
        if failure == "build":
            raise ProcessingError("Build failed")
        write_scene(output, "candidate")
        if failure == "invalid":
            (output / "model.glb").write_bytes(b"bad")

    service = SimpleNamespace(settings=SimpleNamespace(), execute=execute)
    result = visual_review.improve(
        service, Path("source.mov"), None, baseline, lambda **k: None, lambda: None
    )
    assert load_scene(baseline)[0].scale_note == "baseline"
    assert result["status"] == "kept_initial"


def test_cancellation_does_not_turn_into_success(baseline, monkeypatch):
    def stop():
        raise Cancelled()

    with pytest.raises(Cancelled):
        visual_review.improve(
            SimpleNamespace(), Path("x.mov"), None, baseline, lambda **k: None, stop
        )


def test_review_uses_source_and_preview_images_and_validates_evidence(baseline, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test")

    async def call(key, settings, parts, check, declaration):
        assert len([p for p in parts if p.inline_data]) == 4
        return SimpleNamespace(
            function_calls=[
                SimpleNamespace(
                    name=gemini.REVIEW_FUNCTION,
                    args=dict(
                        score=60,
                        needs_correction=True,
                        summary="Wrong layout",
                        issues=[dict(description="Missing shelf", source_frames=[99])],
                    ),
                )
            ]
        )

    monkeypatch.setattr(gemini, "request_function", call)
    with pytest.raises(ProcessingError, match="Visual review unavailable"):
        gemini.review(baseline, SimpleNamespace(), lambda: None)


def test_review_rate_limit_is_actionable_and_sanitized(baseline, monkeypatch):
    monkeypatch.setattr(gemini, "load_key", lambda _: "test-secret")

    class Quota(Exception):
        code = 429

    async def fail(*args):
        raise Quota("test-secret private payload")

    monkeypatch.setattr(gemini, "request_function", fail)
    with pytest.raises(ProcessingError, match="rate limit/quota reached") as error:
        gemini.review(baseline, SimpleNamespace(), lambda: None)
    assert "test-secret" not in str(error.value)
    assert json.loads((baseline / "review-error.json").read_text())["status"] == 429


def test_initial_review_failure_retains_model_with_visible_warning(baseline, monkeypatch):
    def fail(*args):
        raise ProcessingError("Visual review paused: Gemini rate limit/quota reached (429).")

    monkeypatch.setattr(gemini, "review", fail)
    report = visual_review.improve(
        SimpleNamespace(settings=None),
        Path("x.mov"),
        None,
        baseline,
        lambda **k: None,
        lambda: None,
    )
    scene, _, details = load_scene(baseline)
    assert scene.scale_note == "baseline" and report["status"] == "unavailable"
    assert any("429" in w for w in details["warnings"])
