#!/usr/bin/env python3
"""Run the original openai-whisper locally on a video or selected spec windows.

This script only produces a secondary ASR text source. It does not adjudicate
transcript differences or perform translation review.
"""
import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import tempfile
from pathlib import Path

from media_tools import ffmpeg_exe, ffprobe_exe


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_window(value):
    try:
        a, b = value.split(":", 1)
        start, end = float(a), float(b)
    except Exception as exc:
        raise argparse.ArgumentTypeError("window must be START:END in seconds") from exc
    if start < 0 or end <= start:
        raise argparse.ArgumentTypeError("window must satisfy 0 <= START < END")
    return start, end


def merge_windows(windows, context):
    expanded = [(max(0.0, a - context), b + context) for a, b in windows]
    expanded.sort()
    merged = []
    for a, b in expanded:
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def windows_from_spec(path, context):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = []
    for image in data.get("images", []):
        for quote in image.get("quotes", []):
            t = float(quote.get("time", 0))
            raw.append((max(0.0, t - context), t + context))
    if not raw:
        raise SystemExit("spec contains no quote times")
    return merge_windows(raw, 0.0)


def run_ffmpeg(video, start, end, wav):
    subprocess.run([
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{end-start:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)
    ], check=True)


def srt_time(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--spec", type=Path, help="Use quote times from spec.json")
    ap.add_argument("--window", action="append", type=parse_window,
                    help="Explicit absolute seconds window START:END; repeatable")
    ap.add_argument("--context", type=float, default=20.0,
                    help="Seconds of context on each side of quote windows (default: 20)")
    ap.add_argument("--model", default="base.en",
                    help="Original Whisper model, e.g. base.en or small.en")
    ap.add_argument("--language", default="en")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--fp16", action="store_true",
                    help="Use fp16; only enable when the selected device supports it")
    args = ap.parse_args()

    if not args.video.exists():
        raise SystemExit(f"video not found: {args.video}")
    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.spec and args.window:
        raise SystemExit("use either --spec or --window, not both")
    if args.spec:
        windows = windows_from_spec(args.spec, args.context)
    elif args.window:
        windows = merge_windows(args.window, 0.0)
    else:
        # Full-video mode is explicit: use the video duration reported by ffprobe.
        probe = subprocess.run([ffprobe_exe(), "-v", "error", "-show_entries",
                                "format=duration", "-of", "default=nw=1:nk=1",
                                str(args.video)], capture_output=True, text=True, check=True)
        windows = [(0.0, float(probe.stdout.strip()))]

    try:
        import whisper
    except ImportError as exc:
        raise SystemExit(
            "openai-whisper is not installed. Install it in the skill venv with "
            "uv pip install --python <SKILL_DIR>/.venv/bin/python openai-whisper"
        ) from exc

    print(f"loading openai-whisper {args.model} on {args.device}", flush=True)
    model = whisper.load_model(args.model, device=args.device)
    all_segments = []
    with tempfile.TemporaryDirectory(prefix="local_whisper_") as tmp:
        for idx, (start, end) in enumerate(windows, 1):
            wav = Path(tmp) / f"window_{idx:03d}.wav"
            print(f"transcribing window {idx}: {start:.3f}-{end:.3f}s", flush=True)
            run_ffmpeg(args.video, start, end, wav)
            result = model.transcribe(
                str(wav), language=args.language, task="transcribe",
                fp16=args.fp16, temperature=0, condition_on_previous_text=True,
                verbose=False,
            )
            for seg in result.get("segments", []):
                all_segments.append({
                    "start": round(float(seg["start"]) + start, 3),
                    "end": round(float(seg["end"]) + start, 3),
                    "text": seg["text"].strip(),
                    "window": idx,
                })

    metadata = {
        "engine": "openai-whisper",
        "engine_version": importlib.metadata.version("openai-whisper"),
        "model": args.model,
        "model_source": getattr(whisper, "_MODELS", {}).get(args.model),
        "language": args.language,
        "device": args.device,
        "fp16": bool(args.fp16),
        "video": str(args.video),
        "video_sha256": sha256(args.video),
        "spec": str(args.spec) if args.spec else None,
        "spec_sha256": sha256(args.spec) if args.spec else None,
        "context_seconds": args.context,
        "windows_absolute_seconds": [[round(a, 3), round(b, 3)] for a, b in windows],
        "purpose": "secondary ASR text source; requires separate diff and structured adjudication",
    }
    payload = {"metadata": metadata, "segments": all_segments}
    (args.out_dir / "asr_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "asr_segments.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.out_dir / "asr_transcript.srt").open("w", encoding="utf-8") as f:
        for i, seg in enumerate(all_segments, 1):
            f.write(f"{i}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{seg['text']}\n\n")
    print(f"wrote {len(all_segments)} segments to {args.out_dir}")


if __name__ == "__main__":
    main()
