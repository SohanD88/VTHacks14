"""Replace this provider with capture/CV/reconstruction; keep the scene contract stable."""

from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.schemas import Detection, Room, ScanRequest, ScanResponse, ScanStats, Scene, SceneObject


class ReconstructionService(Protocol):
    def reconstruct(self, request: ScanRequest) -> ScanResponse: ...


class MockReconstructionService:
    """Deterministic fixtures, never inferred from a real camera or uploaded media."""

    def reconstruct(self, request: ScanRequest) -> ScanResponse:
        started = perf_counter()
        if request.preset == "office":
            room = Room(
                id="room-01", name="Operations room", center=(0, 1.25, 0), size=(8, 2.5, 6.6)
            )
            specs = [
                ("desk", "Workstation 01", (-1.85, 0.36, -1.275), (1.7, 0.72, 0.85), 0.96),
                ("desk", "Workstation 02", (1.6, 0.4, -2.025), (2.3, 0.8, 0.75), 0.94),
                ("cabinet", "Equipment storage", (2.3, 0.5, 1.025), (1.7, 1, 1.25), 0.91),
                ("chair", "Chair 01", (-1.875, 0.475, 1.625), (0.75, 0.95, 0.75), 0.93),
                ("chair", "Chair 02", (0.21, 0.36, 0.91), (0.72, 0.72, 0.72), 0.90),
                ("door", "Entry D-01", (3, 1, -3.25), (1, 2, 0.1), 0.89),
            ]
            path = [(-3.6, 0.06, 2.8), (-2.6, 0.06, 1.6), (-1.2, 0.06, 0.8), (0.2, 0.06, -0.2)]
            frames, keyframes, coverage = 127, 42, 62
        else:
            room = Room(id="room-01", name="East corridor", center=(0, 1.4, 0), size=(4, 2.8, 10))
            specs = [
                ("door", "Entry D-01", (-1.95, 1, -3), (0.1, 2, 1), 0.92),
                ("door", "Entry D-02", (1.95, 1, 1), (0.1, 2, 1), 0.90),
                ("cabinet", "Storage C-01", (1.45, 0.6, -4), (0.8, 1.2, 1.1), 0.87),
                ("person", "Demo person", (-0.5, 0.85, -0.6), (0.45, 1.7, 0.45), 0.95),
            ]
            path = [(0, 0.06, 4.4), (0.2, 0.06, 2), (-0.1, 0.06, 0), (0.2, 0.06, -2)]
            frames, keyframes, coverage = 84, 28, 48

        objects = [
            SceneObject(
                id=f"object-{i:02}",
                kind=kind,
                label=label,
                position=position,
                size=size,
                confidence=confidence,
            )
            for i, (kind, label, position, size, confidence) in enumerate(specs, 1)
        ]
        counts = Counter(obj.kind for obj in objects)
        detections = [
            Detection(
                kind=kind,
                count=count,
                confidence=round(sum(o.confidence for o in objects if o.kind == kind) / count, 2),
            )
            for kind, count in sorted(counts.items())
        ]
        return ScanResponse(
            id=uuid4(),
            name=request.name,
            preset=request.preset,
            created_at=datetime.now(timezone.utc),
            processing_ms=round((perf_counter() - started) * 1000),
            message="Demo reconstruction complete. Geometry and detections are simulated.",
            scene=Scene(rooms=[room], objects=objects, camera_path=path),
            detections=detections,
            stats=ScanStats(
                rooms_mapped=1,
                objects=len(objects),
                frames=frames,
                keyframes=keyframes,
                coverage_percent=coverage,
            ),
        )
