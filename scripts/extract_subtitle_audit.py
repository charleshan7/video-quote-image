#!/usr/bin/env python3
"""Extract source/cropped samples for a human burned-subtitle audit."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from extract_frame_candidates import duration, extract, sha256
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--policy", choices=["verified-absent", "cropped"], required=True)
    ap.add_argument("--crop-bottom", type=float, default=0.0)
    ap.add_argument("--time", action="append", type=float, default=[])
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--out-dir", default="audit/subtitle_samples")
    ap.add_argument("--audit", default="audit/subtitle_audit.json")
    args = ap.parse_args()

    root = args.root.resolve()
    video = args.video if args.video.is_absolute() else root / args.video
    out_dir = root / args.out_dir
    audit_path = root / args.audit
    if args.policy == "cropped" and not 0 < args.crop_bottom < 0.5:
        raise SystemExit("cropped policy requires 0 < --crop-bottom < 0.5")
    if args.policy == "verified-absent" and args.crop_bottom:
        raise SystemExit("verified-absent may not use --crop-bottom")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"subtitle sample directory is not empty: {out_dir}")
    if audit_path.exists():
        raise SystemExit(f"subtitle audit already exists: {audit_path}")

    video_duration = duration(video)
    times = args.time or [video_duration * 0.1, video_duration * 0.5, video_duration * 0.9]
    if len(times) < 3:
        raise SystemExit("at least three --time samples are required")
    samples = []
    for index, second in enumerate(times, 1):
        source = out_dir / f"sample-{index:02d}-source.jpg"
        processed = out_dir / f"sample-{index:02d}-processed.jpg"
        extract(video, second, source)
        if args.policy == "cropped":
            with Image.open(source) as image:
                keep = round(image.height * (1 - args.crop_bottom))
                image.crop((0, 0, image.width, keep)).save(processed, quality=95, subsampling=0)
        else:
            processed.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, processed)
        samples.append({
            "time": round(second, 3),
            "source_artifact": str(source.relative_to(root)),
            "source_sha256": sha256(source),
            "processed_artifact": str(processed.relative_to(root)),
            "processed_sha256": sha256(processed),
            "decision": "review-required",
        })

    audit = {
        "source_video_sha256": sha256(video),
        "policy": args.policy,
        "crop_bottom": args.crop_bottom,
        "reviewer": args.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "samples": samples,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"inspect {out_dir} at original size, then replace every decision=review-required")


if __name__ == "__main__":
    main()
