"""Discover and submit real videos through HTTP; keep scene, metrics and input hashes."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.video import discover_videos  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--api", default="http://127.0.0.1:8014/api")
    parser.add_argument("--mode", choices=["quick", "balanced", "high"], default="balanced")
    parser.add_argument("--output", type=Path, help="Separate directory for comparison results")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "test-results" / "real-video"
    output.mkdir(parents=True, exist_ok=True)
    videos = discover_videos(root)
    if len(videos) < 2:
        raise SystemExit("At least two evaluation videos are required")
    results, manifest = [], []
    with httpx.Client(timeout=120) as client:
        for video in videos:
            with video.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
                source.seek(0)
                response = client.post(
                    args.api + "/scans",
                    files={"file": (video.name, source, "application/octet-stream")},
                    data={"name": video.stem + " " + args.mode, "mode": args.mode},
                )
            response.raise_for_status()
            job = response.json()
            id = job["id"]
            print(f"{video.name}: {id}", flush=True)
            last = None
            deadline = time.monotonic() + 1800
            while job["status"] not in {"completed", "degraded", "failed", "cancelled"}:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Job {id} remains active; inspect it before retrying.")
                time.sleep(2)
                response = client.get(args.api + f"/scans/{id}/status")
                response.raise_for_status()
                job = response.json()
                state = (job["stage"], job["progress"])
                if state != last:
                    print(video.name, *state, flush=True)
                    last = state
            response = client.get(args.api + f"/scans/{id}")
            response.raise_for_status()
            job = response.json()
            # A content hash avoids collisions when different folders contain the same basename.
            result_file = f"{video.stem}-{digest[:8]}-{args.mode}.json"
            (output / result_file).write_text(json.dumps(job))
            results.append({k: v for k, v in job.items() if k != "scene"})
            manifest.append(
                {
                    "video": str(video.relative_to(root)),
                    "sha256": digest,
                    "scan_id": id,
                    "result_file": result_file,
                }
            )
            print(job["status"], job["message"], job["stats"], flush=True)
            if job["status"] in {"failed", "cancelled"}:
                raise SystemExit(1)
    (output / f"summary-{args.mode}.json").write_text(json.dumps(results, indent=2))
    (output / f"manifest-{args.mode}.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
