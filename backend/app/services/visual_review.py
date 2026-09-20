"""One bounded visual correction with a validated original kept as a fallback."""

import json
import shutil

from app.services.video import ProcessingError

ARTIFACTS = (
    "model.glb",
    "model.blend",
    "blender-scene.json",
    "generated.blend",
    "gemini-scene.py",
    "gemini-generation.json",
    "blender.log",
    "review-view-0.png",
    "review-view-1.png",
    "review-view-2.png",
)


def improve(service, path, scan, output, update, check):
    from app.services import gemini
    from app.services.blender import load_scene

    load_scene(output)  # Never preserve an invalid baseline as a successful result.
    report = {"status": "unavailable", "corrected": False, "initial": None, "final": None}
    candidate = output / "review-candidate"
    try:
        update(
            stage="reviewing", message="Comparing Blender views with the source video", progress=65
        )
        check()
        initial = gemini.review(output, service.settings, check)
        report.update(initial=initial, final=initial, status="reviewed")
        if initial["needs_correction"]:
            candidate.mkdir(exist_ok=True)
            metadata = json.loads((output / "gemini-generation.json").read_text())
            inputs = (
                ["gemini-generation.json", "gemini-scene.py"]
                + [f"frame-{index:06}.jpg" for index in metadata["source_frames"]]
                + [f"review-view-{index}.png" for index in range(3)]
            )
            for name in inputs:
                shutil.copyfile(output / name, candidate / name)
            update(
                stage="correcting",
                message="Correcting visible layout and furnishing mismatches",
                progress=72,
            )
            source = gemini.generate(
                path,
                scan,
                candidate,
                service.settings,
                update,
                check,
                previous=(output / "gemini-scene.py").read_text(),
                failure="Apply the supplied visual review; keep correct details.",
                visual_feedback=initial,
            )
            # Do not mistake copied baseline previews for candidate previews after a render failure.
            for index in range(3):
                (candidate / f"review-view-{index}.png").unlink(missing_ok=True)

            def building(**patch):
                patch["progress"] = 77
                update(**patch)

            service.execute(source, candidate, building, check)
            load_scene(candidate)
            update(
                stage="reviewing",
                message="Checking the corrected model against the footage",
                progress=85,
            )
            corrected = gemini.review(candidate, service.settings, check)
            report["candidate"] = corrected
            check()
            if corrected["score"] > initial["score"] and len(corrected["issues"]) <= len(
                initial["issues"]
            ):
                backup = output / "before-review"
                backup.mkdir(exist_ok=True)
                for name in ARTIFACTS:
                    if (output / name).exists():
                        shutil.copyfile(output / name, backup / name)
                try:
                    for name in ARTIFACTS:
                        if (candidate / name).exists():
                            shutil.copyfile(candidate / name, output / name)
                except OSError:
                    for name in ARTIFACTS:
                        if (backup / name).exists():
                            shutil.copyfile(backup / name, output / name)
                    raise
                report.update(status="corrected", corrected=True, final=corrected)
            else:
                report["status"] = "kept_initial"
    except (ProcessingError, OSError, ValueError) as exc:
        report["status"] = "kept_initial" if report["initial"] else "unavailable"
        report["note"] = (
            str(exc)
            if isinstance(exc, ProcessingError) and str(exc).startswith("Visual review")
            else "Visual review/correction could not finish; kept the first valid model."
        )
        report["error_type"] = type(exc).__name__
    finally:
        # Cancelled is deliberately not caught: the job stays cancelled, not successful.
        (output / "gemini-review.json").write_text(json.dumps(report, indent=2))
        shutil.rmtree(candidate, ignore_errors=True)
    details_path = output / "blender-scene.json"
    details = json.loads(details_path.read_text())
    warnings = details.setdefault("warnings", [])
    if report["status"] == "unavailable":
        warnings.append(
            report.get("note", "Visual review unavailable; inspect this model against the video.")
        )
    else:
        warnings.append(
            "Visual review: "
            + ("one correction applied. " if report["corrected"] else "initial model retained. ")
            + report["final"]["summary"]
        )
        warnings.extend(
            "Review concern: " + issue["description"] for issue in report["final"]["issues"][:5]
        )
        if report.get("note"):
            warnings.append(report["note"])
    warnings.append(
        "AI visual review does not verify dimensions, hidden surfaces, or safe exit routes."
    )
    details_path.write_text(json.dumps(details))
    return report
