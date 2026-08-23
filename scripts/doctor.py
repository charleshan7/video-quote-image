#!/usr/bin/env python3
"""Check runtime dependencies before starting a video-quote-image project."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import shutil
import sys

from media_tools import assert_font_glyphs, ffmpeg_exe, ffprobe_exe, resolve_font


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-local-asr", action="store_true")
    ap.add_argument("--mode", choices=["render", "download", "cloud-asr", "maintain", "full"],
                    default="render", help="只检查当前任务真正需要的依赖")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = {"python": sys.version.split()[0], "mode": args.mode, "ok": {}, "missing": {}}

    modules = ["PIL", "imageio_ffmpeg", "jsonschema"]
    if args.mode == "maintain":
        modules.extend(["yaml", "ruff"])
    for module in modules:
        try:
            importlib.import_module(module)
            distribution = {"PIL": "Pillow", "yaml": "PyYAML"}.get(module, module)
            report["ok"][module] = importlib.metadata.version(distribution)
        except Exception as exc:  # noqa: BLE001 - report import failure without crashing doctor
            report["missing"][module] = str(exc)
    if args.require_local_asr:
        try:
            importlib.import_module("whisper")
            report["ok"]["whisper"] = "installed"
        except Exception as exc:  # noqa: BLE001 - report optional ASR import failure
            report["missing"]["whisper"] = str(exc)

    for name, finder in (("ffmpeg", ffmpeg_exe), ("ffprobe", ffprobe_exe)):
        try:
            report["ok"][name] = finder()
        except SystemExit as exc:
            report["missing"][name] = str(exc)
    required_tools = {
        "render": (),
        "download": ("yt-dlp",),
        "cloud-asr": ("curl",),
        "maintain": ("yt-dlp", "curl", "rsync"),
        "full": ("yt-dlp", "curl", "rsync"),
    }[args.mode]
    for name in required_tools:
        path = shutil.which(name)
        (report["ok"] if path else report["missing"])[name] = path or "not on PATH"

    font_checks = (("cjk_bold", "中文测试"), ("cjk_regular", "人物访谈"), ("latin", "Quote 123"))
    for kind, sample in font_checks:
        try:
            path = resolve_font(kind)
            assert_font_glyphs(path, sample, kind)
            report["ok"][kind] = path
        except SystemExit as exc:
            report["missing"][kind] = str(exc)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for name, value in report["ok"].items():
            print(f"OK      {name}: {value}")
        for name, value in report["missing"].items():
            print(f"MISSING {name}: {value}")
    return 1 if report["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
