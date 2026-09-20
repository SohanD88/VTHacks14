"""Real frame-to-depth-to-pose-to-semantic-mesh orchestration."""

import json
import sys
from collections import Counter
from time import perf_counter

import numpy as np

from app.services.geometry import Fusion, Tracker, write_ply
from app.services.registration import refine_views
from app.services.relocalization import recover_views
from app.services.video import ProcessingError, extract

try:
    import resource  # Unix only
except ImportError:  # Windows has no 'resource' module
    resource = None


def _peak_memory_mb() -> float:
    """Peak memory of this process in MB. Reporting only; never allowed to fail a scan."""
    try:
        if resource is not None:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return round(peak / (1024**2 if sys.platform == "darwin" else 1024), 1)
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return round(counters.PeakWorkingSetSize / 1024**2, 1)
    except Exception:
        pass
    return 0.0


class ReconstructionService:
    def __init__(self, models):
        self.models = models

    def reconstruct(self, path, scan, output, update, check):
        started = perf_counter()
        frames, report, decoded = extract(
            path, scan.video, output, scan.processing_mode, update, check
        )
        (output / "frame-quality.json").write_text(json.dumps(report, indent=2))
        rejected = Counter(r["reason"] for r in report if r["reason"] != "accepted")
        update(
            stage="loading_models",
            progress=20,
            frames=decoded,
            accepted=len(frames),
            rejected=decoded - len(frames),
            keyframes=len(frames),
            rejection_reasons=dict(rejected),
        )
        self.models.load()
        check()
        update(execution_device=self.models.device)
        tracker = Tracker()
        fusion = Fusion(
            self.models.labels, step={"quick": 5, "balanced": 5, "high": 6}[scan.processing_mode]
        )
        depth_ms = semantic_ms = geometry_ms = 0
        observations = []
        dynamic_ids = [
            k
            for k, v in self.models.labels.items()
            if v.split(",")[0] in {"person", "animal", "car", "bicycle"}
        ]
        for i, (frame, rgb) in enumerate(frames):
            check()
            update(
                stage="depth_and_semantics", message=f"Analyzing keyframe {i + 1} of {len(frames)}"
            )
            depth, labels, confidence, dt, st, detections = self.models.infer(rgb)
            depth_ms += dt
            semantic_ms += st
            self.models.diagnostics(rgb, depth, labels, confidence, output, frame, detections)
            (output / f"detections-{frame:06}.json").write_text(json.dumps(detections))
            check()
            ts = perf_counter()
            tracker.track(rgb, depth, labels, dynamic_ids, frame)
            observations.append((frame, rgb, depth, labels, confidence, detections))
            geometry_ms += (perf_counter() - ts) * 1000
            update(
                stage="tracking_and_fusion",
                progress=20 + 55 * (i + 1) / len(frames),
                poses=len(tracker.views),
                pose_failures=tracker.failures,
                depth_ms=round(depth_ms),
                semantic_ms=round(semantic_ms),
                geometry_ms=round(geometry_ms),
            )
        if not tracker.views:
            raise ProcessingError(
                (
                    "Camera tracking failed on all frames. Record a well-lit textured "
                    "room with slow overlapping movement."
                )
            )
        check()
        update(
            stage="relocalizing",
            progress=75,
            message="Recovering missed views from shared features",
        )
        ts = perf_counter()
        recovered, recovery = recover_views(tracker.views, tracker.failed_views, check)
        recovered_by_frame = {view["frame"]: view for view in recovered}
        observations_by_frame = {observation[0]: observation for observation in observations}
        for details in recovery:
            frame = details["frame"]
            observations_by_frame[frame][2][:] *= details["depth_scale_alignment"]
            record = next(record for record in tracker.records if record["frame"] == frame)
            record.update(
                details,
                success=True,
                recovered=True,
                camera_to_initial_camera=recovered_by_frame[frame]["pose"].tolist(),
            )
        tracker.views = sorted(tracker.views + recovered, key=lambda view: view["frame"])
        tracker.failures -= len(recovered)
        observations = [observations_by_frame[view["frame"]] for view in tracker.views]
        geometry_ms += (perf_counter() - ts) * 1000
        update(poses=len(tracker.views), pose_failures=tracker.failures)
        update(
            stage="joint_registration",
            progress=75,
            message="Checking shared features across overlapping and return views",
        )
        ts = perf_counter()
        poses, scales, registration = refine_views(tracker.views, check)
        (output / "registration.json").write_text(json.dumps(registration, indent=2))
        for i, ((frame, rgb, depth, labels, confidence, detections), pose, scale) in enumerate(
            zip(observations, poses, scales)
        ):
            check()
            depth *= scale
            np.save(output / f"depth-refined-{frame:06}.npy", depth)
            features = dict(tracker.views[i], pose=pose, xyz=tracker.views[i]["xyz"] * scale)
            fusion.add(rgb, depth, labels, confidence, pose, frame, detections, features)
            record = next(r for r in tracker.records if r["frame"] == frame)
            record["refined_camera_to_initial_camera"] = pose.tolist()
            record["joint_depth_scale"] = float(scale)
            update(
                stage="fusing_refined_views",
                progress=78 + 7 * (i + 1) / len(observations),
                message=f"Fusing localized view {i + 1} of {len(observations)}",
            )
        geometry_ms += (perf_counter() - ts) * 1000
        (output / "camera-poses.json").write_text(json.dumps(tracker.records, indent=2))
        update(stage="meshing", progress=85)
        ts = perf_counter()
        scene, floor_found = fusion.finish(check)
        (output / "fixture-fit.json").write_text(json.dumps(fusion.fixture_report, indent=2))
        (output / "opening-fit.json").write_text(json.dumps(fusion.opening_report, indent=2))
        (output / "motion-report.json").write_text(json.dumps(fusion.motion_report, indent=2))
        (output / "instance-tracks.json").write_text(json.dumps(fusion.instance_report, indent=2))
        (output / "structure-fit.json").write_text(json.dumps(fusion.structure_report, indent=2))
        geometry_ms += (perf_counter() - ts) * 1000
        if not scene.objects:
            raise ProcessingError(
                (
                    "No reliable scene geometry was recovered. Try higher quality or a"
                    " slower recording."
                )
            )
        warnings = [
            "Wall planes and nearby window/screen surfaces are fitted to observed evidence. "
            "Unsupported wall observations remain in the uncertain layer; gaps are unobserved.",
            "Recognizable furniture fits use size priors and estimated floor support. "
            "Toggle observed surfaces to compare the evidence.",
            (
                "Monocular depth and assumed intrinsics provide approximate scale,"
                " not measured dimensions."
            ),
            (
                "Only observed surfaces are reconstructed. Hidden furniture backs "
                "and unseen room areas remain empty."
            ),
            (
                "Semantic labels and openings are model predictions; an opening ca"
                "ndidate is not a verified exit."
            ),
        ]
        moving = sum(obj.transient for obj in scene.objects)
        if moving:
            warnings.append(
                f"{moving} moving candidates are retained as observed snapshots "
                "in a separate, initially hidden layer."
            )
        warnings.append(
            "Motion checks need repeated visual features and a stable background; "
            "some moving objects may remain undetected."
        )
        if not registration["accepted"]:
            warnings.append(
                "Joint registration did not improve both consistency measures; "
                "the original accepted poses were retained."
            )
        if decoded < scan.video.total_frames - 2:
            warnings.append(
                "The decoder stopped before the declared end. Output uses readable frames only."
            )
        if tracker.failures:
            warnings.append(
                f"{tracker.failures} keyframes could not be localized "
                "and were excluded from fusion."
            )
        if not floor_found:
            warnings.append(
                (
                    "A stable floor plane could not be fitted. Scene orientation and s"
                    "upport heights remain uncertain."
                )
            )
        if not any(o.entrance for o in scene.objects):
            warnings.append(
                "No entrance detected; this does not establish that the room has no exit."
            )
        if not any(o.movable for o in scene.objects):
            warnings.append("No furniture recognized. Visible structural surfaces are retained.")
        trajectory = np.array(scene.camera_path)
        travel = (
            float(np.linalg.norm(np.diff(trajectory, axis=0), axis=1).sum())
            if len(trajectory) > 1
            else 0
        )
        if travel < 0.25:
            warnings.append(
                (
                    "Limited camera translation: hidden surfaces and relative distance"
                    "s are particularly uncertain."
                )
            )
        stats = scan.stats
        stats.tracking_success_rate = round(len(fusion.frames) / len(frames), 3)
        stats.objects = len(scene.objects)
        stats.entrances = sum(o.entrance for o in scene.objects)
        stats.tracked_objects = sum(len(o.source_frames) > 1 for o in scene.objects)
        stats.duplicate_observations_merged = fusion.merged
        stats.geometry_ms = round(geometry_ms)
        stats.vertices = sum(len(o.geometry.vertices) for o in scene.objects)
        stats.peak_memory_mb = _peak_memory_mb()
        scan.scene = scene
        scan.warnings = warnings
        scan.processing_ms = round((perf_counter() - started) * 1000)
        stats.average_frame_ms = round(scan.processing_ms / max(1, decoded), 2)
        counts = Counter(o.kind for o in scene.objects)
        scan.detections = [
            dict(
                kind=k,
                count=v,
                confidence=round(
                    float(np.mean([o.confidence for o in scene.objects if o.kind == k])), 3
                ),
            )
            for k, v in counts.items()
        ]
        # This method cannot verify complete metric reconstruction; never report full certainty.
        scan.status = "degraded"
        scan.stage = "finished"
        scan.progress = 100
        scan.message = (
            "Partial observed-surface reconstruction ready. Review uncertainty"
            " and source evidence before editing."
        )
        write_ply(scene, output / "cloud.ply")
        (output / "scene.json").write_text(scene.model_dump_json())
        stats.artifact_bytes = (output / "scene.json").stat().st_size
        (output / "metrics.json").write_text(scan.model_dump_json(indent=2, exclude={"scene"}))
        return scan
