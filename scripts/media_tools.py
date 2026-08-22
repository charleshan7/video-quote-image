#!/usr/bin/env python3
"""Locate ffmpeg/ffprobe the same way across every script in this skill.

requirements.txt installs imageio-ffmpeg, which ships an ffmpeg binary but
*not* ffprobe. Scripts that assume a bare `ffmpeg`/`ffprobe` on PATH work on a
developer Mac and fail on a machine that only has the skill venv, so resolve
both here and fail with an actionable message instead of a FileNotFoundError.
"""
import shutil


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit(
            "找不到 ffmpeg。安装本 skill 依赖（pip install -r requirements.txt，"
            "自带 imageio-ffmpeg），或用系统包管理器装 ffmpeg。"
        )
    return found


def ffprobe_exe() -> str:
    # imageio-ffmpeg does not bundle ffprobe, so this one really needs a host install.
    found = shutil.which("ffprobe")
    if not found:
        raise SystemExit(
            "找不到 ffprobe。imageio-ffmpeg 不包含 ffprobe，需要单独安装："
            "macOS 用 brew install ffmpeg，Debian/Ubuntu 用 apt install ffmpeg。"
        )
    return found
