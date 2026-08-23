#!/usr/bin/env python3
"""Extract auditable hero/quote frame candidates and scaffold frame_audit.json."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from media_tools import ffmpeg_exe, ffprobe_exe


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def duration(video: Path) -> float:
    result = subprocess.run(
        [ffprobe_exe(), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def bounded_times(center: float, offsets: list[float], video_duration: float) -> list[float]:
    times: list[float] = []
    end_margin = min(0.25, max(0.01, video_duration / 10))
    latest = max(0.0, video_duration - end_margin)
    for offset in offsets:
        value = round(min(max(0.0, center + offset), latest), 3)
        if value not in times:
            times.append(value)
    for attempt in range(1, 1001):
        if len(times) >= len(offsets):
            break
        direction = -1 if attempt % 2 else 1
        step = ((attempt + 1) // 2) * 0.025
        candidate = round(
            min(max(0.0, center + direction * step), latest), 3
        )
        if candidate not in times:
            times.append(candidate)
    if len(times) < len(offsets):
        raise SystemExit("video is too short to produce distinct frame candidate timestamps")
    return times[:len(offsets)]


def extract(video: Path, second: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{second:.3f}", "-i", str(video), "-frames:v", "1",
         "-q:v", "2", str(output)],
        capture_output=True, check=True,
    )
    if not output.exists() or output.stat().st_size == 0:
        raise SystemExit(f"failed to extract frame at {second:.3f}s")


def evidence(root: Path, video: Path, times: list[float], folder: Path,
             prefix: str) -> list[dict]:
    rows = []
    for index, second in enumerate(times, 1):
        path = folder / f"{prefix}-{index:02d}.jpg"
        extract(video, second, path)
        rows.append({
            "time": second,
            "artifact": str(path.relative_to(root)),
            "sha256": sha256(path),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--spec", default="audit/spec.json")
    ap.add_argument("--out-dir", default="audit/frames")
    ap.add_argument("--audit", default="audit/frame_audit.json")
    ap.add_argument("--reviewer", required=True)
    args = ap.parse_args()

    root = args.root.resolve()
    video = args.video if args.video.is_absolute() else root / args.video
    spec_path = root / args.spec
    out_dir = root / args.out_dir
    audit_path = root / args.audit
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"candidate output directory is not empty: {out_dir}")
    if audit_path.exists():
        raise SystemExit(f"frame audit already exists: {audit_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    video_duration = duration(video)

    heroes = []
    image_rows = []
    for image in spec.get("images", []):
        image_id = str(image["id"])
        folder = out_dir / image_id
        hero_time = float(image["hero_time"])
        hero_times = bounded_times(hero_time, [-12, -8, -4, -2, 0, 2, 4, 8], video_duration)
        heroes.append({
            "image_id": image_id,
            "hero_subject": image.get("hero_subject", ""),
            "hero_subject_role": image.get("hero_subject_role", ""),
            "chosen_hero_time": hero_time,
            "chosen_reason": "",
            "candidates": evidence(root, video, hero_times, folder, "hero"),
        })
        rows = []
        for quote in image.get("quotes", []):
            quote_id = str(quote["quote_id"])
            chosen = float(quote.get("frame_time", quote["time"]))
            quote_times = bounded_times(chosen, [-2, -1, 0, 1, 2], video_duration)
            rows.append({
                "quote_id": quote_id,
                "chosen_frame_time": chosen,
                "chosen_reason": "",
                "candidates": evidence(root, video, quote_times, folder, quote_id),
            })
        image_rows.append({"image_id": image_id, "rows": rows})

    audit = {
        "source_video_sha256": sha256(video),
        "reviewer": args.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "heroes": heroes,
        "images": image_rows,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote candidate frames to {out_dir}")
    print(f"review every candidate, update chosen times/reasons, then save {audit_path}")


if __name__ == "__main__":
    main()
