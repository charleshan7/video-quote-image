#!/usr/bin/env python3
"""Check runtime dependencies before starting a video-quote-image project."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path

from media_tools import assert_font_glyphs, ffmpeg_exe, ffprobe_exe, resolve_font


def read_requirements() -> dict[str, str]:
    """读 requirements.txt，返回 {发行包名: 原始约束}。不递归 -r，基础清单就够。"""
    path = Path(__file__).resolve().parent.parent / "requirements.txt"
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[]", line, 1)[0].strip()
        if name:
            found[name] = line
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-local-asr", action="store_true")
    ap.add_argument("--mode", choices=["render", "download", "cloud-asr", "maintain", "full"],
                    default="render", help="只检查当前任务真正需要的依赖")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = {"python": sys.version.split()[0], "mode": args.mode, "ok": {}, "missing": {}}

    # 逐条核对 requirements.txt 里声明的发行包是否真的装进了当前解释器。
    # 只列 import 名会漏：fonttools 曾经写在 requirements 里但 venv 没装，
    # doctor 全绿，直到渲染跑到字形校验那一步才崩。
    for dist, spec in read_requirements().items():
        try:
            report["ok"][dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            report["missing"][dist] = (
                f"requirements.txt 声明了 {spec}，但当前 venv 没装；"
                f"跑 uv pip install -r requirements.txt 同步")

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
