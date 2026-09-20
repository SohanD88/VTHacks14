"""Validate and package a built lounge for the one-click demo loader.
Run with backend/.venv/bin/python .../package_lounge.py /path/to/blender/output
"""

import gzip
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
from app.services.blender import load_scene  # noqa: E402

source = Path(sys.argv[1]).resolve()
destination = BACKEND / "demo_assets" / "virginia-lounge"
destination.mkdir(parents=True, exist_ok=True)
scene, raw, details = load_scene(source)
scene.camera_frames = []
scene.camera_path = []
payload = {"scene": scene.model_dump(mode="json"), "warnings": details["warnings"]}
(destination / "scene.json.gz").write_bytes(
    gzip.compress(json.dumps(payload, separators=(",", ":")).encode(), mtime=0)
)
shutil.copyfile(source / "lounge.blend", destination / "model.blend")
print(
    json.dumps(
        {
            "objects": len(scene.objects),
            "vertices": sum(len(o.geometry.vertices) for o in scene.objects),
            "doors": [o.label for o in scene.objects if o.entrance],
            "glb_mb": round(len(raw) / 1e6, 2),
            "bundle_mb": round((destination / "scene.json.gz").stat().st_size / 1e6, 2),
        },
        indent=2,
    )
)
