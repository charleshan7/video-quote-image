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


# 候选写成 "路径" 或 "路径::face序号"。ttc 是字体集合，序号选错会拿到别的字面——
# 例如 STHeiti Medium.ttc 的 face 0 是 Heiti TC（繁体），简体在 face 1。
FONT_CANDIDATES = {
    "cjk_bold": [
        # 思源黑体 Heavy 是本项目定稿字重：简体字面、字重够压住画面
        "~/Library/Fonts/SourceHanSansSC-Heavy.otf",
        "~/Library/Fonts/NotoSansCJKsc-Black.otf",
        "~/Library/Fonts/SourceHanSansSC-Bold.otf",
        "~/Library/Fonts/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc::1",
        "C:/Windows/Fonts/msyhbd.ttc",
    ],
    "cjk_regular": [
        "~/Library/Fonts/SourceHanSansSC-Regular.otf",
        "~/Library/Fonts/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc::1",
        "C:/Windows/Fonts/msyh.ttc",
    ],
    # 拉丁也优先思源：它自带西文字形，中英同族，英文行和时间码不会像外挂上去的
    "latin": [
        "~/Library/Fonts/SourceHanSansSC-Regular.otf",
        "~/Library/Fonts/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


def split_font_spec(spec: str) -> tuple[str, int]:
    """把 "路径::序号" 拆成 (路径, 序号)；没写序号就是 0。"""
    text = str(spec)
    if "::" in text:
        path, _, idx = text.rpartition("::")
        if idx.isdigit():
            return str(Path(path).expanduser()), int(idx)
    return str(Path(text).expanduser()), 0


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
        path, index = split_font_spec(requested)
        if Path(path).is_file():
            # 和候选分支保持一致：一律返回展开后的绝对路径 + 可选 ::face
            return f"{path}::{index}" if index else path
        raise SystemExit(f"font does not exist: {path} ({env_name})")
    for candidate in FONT_CANDIDATES[kind]:
        path, index = split_font_spec(candidate)
        if Path(path).is_file():
            # 返回展开后的绝对路径：调用方要拿它算哈希、写进渲染证据，带 ~ 会打不开
            return f"{path}::{index}" if index else path
    pattern = "Noto Sans CJK SC:style=Bold" if kind == "cjk_bold" else (
        "Noto Sans CJK SC" if kind == "cjk_regular" else "Noto Sans"
    )
    matched = _fontconfig_match(pattern)
    if matched:
        return matched
    raise SystemExit(
        f"no usable {kind} font found; install Noto Sans CJK or pass the corresponding font option"
    )


def assert_font_glyphs(path: str, sample: str, label: str, index: int = 0) -> None:
    """Reject fonts whose cmap lacks any character that will actually be rendered.

    A missing-glyph box is itself a non-empty Pillow mask, so getmask/getbbox is
    not evidence of coverage. Reading the font cmap prevents a Latin-only font
    from silently rendering every Chinese character as the same square.
    """
    import logging

    from fontTools.ttLib import TTFont
    from PIL import ImageFont

    # resolve_font 返回的是 "路径::face序号"，调用方不一定拆过：整串当路径打开
    # 会报 "cannot open resource"，看起来像字体不存在，其实只是没拆。
    path, spec_index = split_font_spec(path)
    if spec_index:
        index = spec_index

    try:
        logging.getLogger("fontTools").setLevel(logging.ERROR)
        ImageFont.truetype(path, 48, index=index)
        ttfont = TTFont(path, fontNumber=index, lazy=True)
        cmap = ttfont.getBestCmap() or {}
    except Exception as exc:
        raise SystemExit(f"cannot load {label} font {path} (face {index}): {exc}") from exc
    finally:
        if "ttfont" in locals():
            ttfont.close()

    # str has no iscontrol() on supported Python versions; filter Unicode control
    # characters explicitly while retaining punctuation and symbols used in copy.
    import unicodedata
    required = {char for char in sample if not char.isspace() and unicodedata.category(char)[0] != "C"}
    missing = sorted({char for char in required if ord(char) not in cmap})
    if missing:
        preview = "".join(missing[:12])
        more = f" and {len(missing) - 12} more" if len(missing) > 12 else ""
        raise SystemExit(
            f"{label} font lacks required glyphs {preview!r}{more}: {path} (face {index})"
        )
