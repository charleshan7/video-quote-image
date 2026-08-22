#!/usr/bin/env python3
"""Locate media binaries and fonts consistently across supported platforms."""
import os
import shutil
import subprocess
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001, S110 - fall through to host ffmpeg discovery
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


FONT_CANDIDATES = {
    "cjk_bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
    ],
    "cjk_regular": [
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ],
    "latin": [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


def _fontconfig_match(pattern: str) -> str | None:
    fc_match = shutil.which("fc-match")
    if not fc_match:
        return None
    result = subprocess.run(
        [fc_match, "-f", "%{file}", pattern], capture_output=True, text=True, check=False
    )
    candidate = result.stdout.strip()
    return candidate if result.returncode == 0 and Path(candidate).is_file() else None


def resolve_font(kind: str, explicit: str | None = None) -> str:
    """Return a usable font path or fail closed; never silently substitute glyphs."""
    if kind not in FONT_CANDIDATES:
        raise ValueError(f"unknown font kind: {kind}")
    env_name = f"VIDEO_QUOTE_IMAGE_{kind.upper()}_FONT"
    requested = explicit or os.environ.get(env_name)
    if requested:
        path = Path(requested).expanduser()
        if path.is_file():
            return str(path)
        raise SystemExit(f"font does not exist: {path} ({env_name})")
    for candidate in FONT_CANDIDATES[kind]:
        if Path(candidate).is_file():
            return candidate
    pattern = "Noto Sans CJK SC:style=Bold" if kind == "cjk_bold" else (
        "Noto Sans CJK SC" if kind == "cjk_regular" else "Noto Sans"
    )
    matched = _fontconfig_match(pattern)
    if matched:
        return matched
    raise SystemExit(
        f"no usable {kind} font found; install Noto Sans CJK or pass the corresponding font option"
    )


def assert_font_glyphs(path: str, sample: str, label: str) -> None:
    """Reject fonts that cannot render the required script."""
    from PIL import ImageFont

    try:
        font = ImageFont.truetype(path, 48)
    except OSError as exc:
        raise SystemExit(f"cannot load {label} font {path}: {exc}") from exc
    missing = []
    for char in sample:
        if char.isspace():
            continue
        try:
            mask = font.getmask(char)
        except Exception:  # noqa: BLE001 - convert any glyph failure into a hard stop
            missing.append(char)
            continue
        if mask.getbbox() is None:
            missing.append(char)
    if missing:
        raise SystemExit(f"{label} font lacks required glyphs {missing}: {path}")
