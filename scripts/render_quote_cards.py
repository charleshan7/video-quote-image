#!/usr/bin/env python3
"""按 spec.json 取帧、叠加金句文字，输出 3:4 竖版长图和总览图。

画面来自原视频，文字由本脚本渲染（原片画面里没有字幕时用这条路）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = shutil.which("ffmpeg")
    if not FFMPEG:
        sys.exit("找不到 ffmpeg；请安装 ffmpeg 或 imageio-ffmpeg")

# macOS 自带中日韩字体；换平台改这里
CJK_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
CJK_REG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
LATIN = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def grab_frame(video, seconds):
    """先粗跳再精解 3 秒，避免长 GOP 视频取错帧。"""
    preseek = max(0.0, seconds - 3.0)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{preseek:.3f}", "-i", str(video),
             "-ss", f"{seconds - preseek:.3f}", "-frames:v", "1", tmp],
            check=True, capture_output=True)
        if not os.path.getsize(tmp):
            sys.exit(f"取帧失败 @ {seconds:.2f}s")
        img = Image.open(tmp).convert("RGB")
        img.load()
        return img
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except OSError:
        return ImageFont.load_default()


def wrap(draw, text, fnt, max_w):
    """按像素宽折行：中日韩逐字断，拉丁按词断。"""
    if re.search(r"[一-鿿぀-ヿ]", text):
        units, joiner = list(text), ""
    else:
        units, joiner = text.split(), " "
    lines, cur = [], []
    for u in units:
        if draw.textlength(joiner.join(cur + [u]), font=fnt) <= max_w or not cur:
            cur.append(u)
        else:
            lines.append(joiner.join(cur))
            cur = [u]
    if cur:
        lines.append(joiner.join(cur))
    return lines


def darken(img, strength):
    """底部渐变压暗，保证叠字可读。"""
    grad = Image.new("L", (1, img.height))
    for y in range(img.height):
        grad.putpixel((0, y), int(255 * strength * (0.35 + 0.65 * y / max(1, img.height - 1))))
    return Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img,
                           grad.resize(img.size))


def auto_darken(img, strength, target, box):
    """按文字覆盖区域的实际亮度补压暗。

    只量 box 内的亮度，不量整条——白墙常常只占文字那一侧，
    整条均值会被暗部拉低，导致该压的没压。
    """
    out = darken(img, strength)
    if target <= 0:
        return out
    patch = out.crop(box).convert("L").resize((24, 24))
    mean = sum(patch.getdata()) / 576
    if mean <= target:
        return out
    alpha = min(0.8, (mean - target) / 255 * 3.2)
    return Image.blend(out, Image.new("RGB", out.size, (0, 0, 0)), alpha)


def hhmm(t):
    return f"{int(t)//60:02d}:{int(t)%60:02d}"


def line_x(d, text, fnt, w, cfg, margin=None):
    m = cfg["margin"] if margin is None else margin
    return (w - d.textlength(text, font=fnt)) / 2 if cfg["align"] == "center" else m


def draw_text_block(img, entries, cfg):
    """画一组文字：先在独立图层上糊一层柔性阴影，再压清晰文字。

    entries: [(text, font, x, y, fill)]
    比硬描边贵一点，但边缘不生硬——描边是等宽黑轮廓，放大看像贴纸；
    阴影是从文字向外衰减的暗场，观感接近影视字幕。
    """
    if cfg["shadow"] > 0:
        layer = Image.new("L", img.size, 0)
        ld = ImageDraw.Draw(layer)
        for text, fnt, x, y, _ in entries:
            # 先按 spread 加粗一圈再模糊，否则细笔画糊完就没了压不住背景
            ld.text((x, y), text, font=fnt, fill=255,
                    stroke_width=cfg["shadow_spread"], stroke_fill=255)
        layer = layer.filter(ImageFilter.GaussianBlur(cfg["shadow"]))
        layer = layer.point(lambda v: int(v * cfg["shadow_opacity"]))
        img.paste(Image.new("RGB", img.size, (0, 0, 0)), mask=layer)

    d = ImageDraw.Draw(img)
    for text, fnt, x, y, fill in entries:
        d.text((x, y), text, font=fnt, fill=fill,
               stroke_width=cfg["stroke"], stroke_fill=(0, 0, 0))


def band(video, item, w, h, cfg):
    # frame_time 让画面帧和引用时间码分离：原句正好落在过亮或杂乱的 b-roll 上时，
    # 换一帧干净的画面，右下角时间码仍标这句话的真实出处。
    img = ImageOps.fit(grab_frame(video, item.get("frame_time", item["time"])), (w, h),
                       Image.Resampling.LANCZOS, centering=(0.5, cfg["band_focus"]))
    m = cfg.get("band_margin") or cfg["margin"]
    text_w = w - m * 2 - (0 if cfg["align"] == "center" else 120)
    f_cn, f_en, f_ts = (font(CJK_BOLD, cfg["cn_size"]), font(LATIN, cfg["en_size"]),
                        font(LATIN, 24))

    # 先排版再压暗：只有知道文字落在哪几行，才能对着那一块取样。
    # 用整条取样会被画面暗部拉低均值，该压的地方压不到。
    probe = ImageDraw.Draw(img)
    cn_lines = wrap(probe, item.get("cn", ""), f_cn, text_w)
    en_lines = (wrap(probe, item.get("en", ""), f_en, text_w)[:2]
                if item.get("en") and cfg["show_en"] else [])

    cn_h, en_h = int(cfg["cn_size"] * 1.27), int(cfg["en_size"] * 1.33)
    block = len(cn_lines) * cn_h + len(en_lines) * en_h + (14 if en_lines else 0)
    y = (h - block) / 2 if cfg["text_pos"] == "center" else h - block - 34

    widest = max([probe.textlength(l, font=f_cn) for l in cn_lines] +
                 [probe.textlength(l, font=f_en) for l in en_lines] + [1.0])
    x0 = (w - widest) / 2 if cfg["align"] == "center" else m
    text_box = (int(max(0, x0)), int(max(0, y)),
                int(min(w, x0 + widest)), int(min(h, y + block)))
    img = auto_darken(img, cfg["band_dim"], cfg["auto_dim"], text_box)

    entries = []
    for line in cn_lines:
        entries.append((line, f_cn, line_x(probe, line, f_cn, w, cfg, m), y, (255, 255, 255)))
        y += cn_h
    if en_lines:
        y += 14
        for line in en_lines:
            entries.append((line, f_en, line_x(probe, line, f_en, w, cfg, m), y,
                            (224, 228, 236)))
            y += en_h
    if cfg["show_ts"]:
        ts = hhmm(item["time"])
        entries.append((ts, f_ts, w - m - probe.textlength(ts, font=f_ts), h - 46,
                        (196, 200, 208)))

    draw_text_block(img, entries, cfg)
    if cfg["rule"]:
        ImageDraw.Draw(img).line((0, 0, w, 0), fill=(38, 40, 46), width=2)
    return img


def hero(video, t, title, w, h, meta, cfg):
    img = ImageOps.fit(grab_frame(video, t), (w, h),
                       Image.Resampling.LANCZOS, centering=(0.5, cfg["hero_focus"]))
    if not cfg["hero_text"]:            # 纯画面开场，文字全部交给下面的字幕条
        return img
    img = darken(img, cfg["hero_dim"])
    d = ImageDraw.Draw(img)
    f_k, f_t, f_s = (font(CJK_REG, 30), font(CJK_BOLD, cfg["title_size"]),
                     font(LATIN, 25))
    m = cfg["margin"]
    lines = wrap(d, title, f_t, w - m * 2)
    step = int(cfg["title_size"] * 1.23)
    y = h - len(lines) * step - 122

    entries = []
    if meta.get("kicker"):
        entries.append((meta["kicker"], f_k, m, y - 54, (232, 176, 92)))
    for line in lines:
        entries.append((line, f_t, m, y, (255, 255, 255)))
        y += step
    if meta.get("footer"):
        entries.append((meta["footer"], f_s, m, h - 60, (188, 192, 200)))

    # 主画面文字块大、阴影半径按标题字号放大，否则大字压不住背景
    hero_cfg = dict(cfg, align="left", shadow=cfg["shadow"] * 1.8,
                    shadow_spread=cfg["shadow_spread"] + 2)
    draw_text_block(img, entries, hero_cfg)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--aspect", default="3:4")
    ap.add_argument("--hero-fraction", type=float, default=0.42)
    ap.add_argument("--cn-size", type=int, default=52)
    ap.add_argument("--en-size", type=int, default=27)
    ap.add_argument("--title-size", type=int, default=78)
    ap.add_argument("--band-dim", type=float, default=0.0,
                help="字幕条底部渐变压暗强度；默认 0=不压，靠文字描边保证可读")
    ap.add_argument("--hero-dim", type=float, default=0.25)
    ap.add_argument("--band-focus", type=float, default=0.42,
                    help="字幕条在原帧上的垂直取景重心，0=顶 1=底")
    ap.add_argument("--hero-focus", type=float, default=0.4)
    ap.add_argument("--auto-dim", type=float, default=0.0,
                    help="字幕条目标平均亮度(0-255)，超过就继续压暗；0=关闭")
    ap.add_argument("--bands", type=int, default=4, help="每张图的字幕条数量")
    ap.add_argument("--margin", type=int, default=56,
                    help="主画面标题的左右留白")
    ap.add_argument("--band-margin", type=int, default=0,
                    help="字幕条文字的左右留白；0=沿用 56。调大可把长句收成一栏，"
                         "避免每行横跨整幅、读起来太平铺")
    ap.add_argument("--align", choices=["left", "center"], default="left")
    ap.add_argument("--text-pos", choices=["bottom", "center"], default="bottom")
    ap.add_argument("--stroke", type=int, default=0,
                help="硬描边宽度；默认 0，可读性交给柔性阴影")
    ap.add_argument("--shadow", type=float, default=9.0,
                    help="文字柔性阴影的高斯模糊半径；0=关闭")
    ap.add_argument("--shadow-opacity", type=float, default=0.78)
    ap.add_argument("--shadow-spread", type=int, default=3,
                    help="模糊前先给文字加粗几像素，细笔画才压得住")
    ap.add_argument("--no-en", action="store_true", help="只留中文")
    ap.add_argument("--no-timestamp", action="store_true")
    ap.add_argument("--no-rule", action="store_true", help="去掉条间分隔线")
    ap.add_argument("--no-hero-text", action="store_true",
                    help="主画面不叠标题，做成纯画面开场")
    args = ap.parse_args()

    aw, ah = (float(x) for x in args.aspect.split(":"))
    W = args.width
    H = round(W * ah / aw)
    hero_h = round(H * args.hero_fraction)
    cfg = {"margin": args.margin, "band_margin": args.band_margin,
           "cn_size": args.cn_size, "en_size": args.en_size,
           "title_size": args.title_size, "band_dim": args.band_dim,
           "hero_dim": args.hero_dim, "band_focus": args.band_focus,
           "hero_focus": args.hero_focus, "align": args.align,
           "text_pos": args.text_pos, "stroke": args.stroke,
           "show_en": not args.no_en, "show_ts": not args.no_timestamp,
           "rule": not args.no_rule, "hero_text": not args.no_hero_text,
           "shadow": args.shadow, "shadow_opacity": args.shadow_opacity,
           "shadow_spread": args.shadow_spread,
           "auto_dim": args.auto_dim}

    spec = json.load(open(args.spec, encoding="utf-8"))
    meta = spec.get("meta", {})
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        sys.exit(f"{out_dir} 非空；换一个输出目录，不覆盖已有成品")
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs = []
    for idx, image in enumerate(spec["images"], 1):
        quotes = image["quotes"]
        n = min(args.bands, len(quotes))
        band_h = (H - hero_h) // n
        canvas = Image.new("RGB", (W, H), "black")
        canvas.paste(hero(args.video, image.get("hero_time", quotes[0]["time"]),
                          image["title"], W, hero_h, meta, cfg), (0, 0))
        y = hero_h
        for i, q in enumerate(quotes[-n:]):
            h = band_h if i < n - 1 else H - y
            canvas.paste(band(args.video, q, W, h, cfg), (0, y))
            y += h
        name = re.sub(r'[\\/:*?"<>|\s]+', "_", image["title"])[:24]
        path = out_dir / f"{idx:02d}_{name}.jpg"
        canvas.save(path, quality=93, subsampling=0)
        outputs.append(path)
        print(f"完成: {path} ({W}x{H})")

    cols = min(4, len(outputs))
    rows = (len(outputs) + cols - 1) // cols
    tw, th = 360, 480
    sheet = Image.new("RGB", (cols * tw, rows * th), "#111111")
    for i, p in enumerate(outputs):
        sheet.paste(ImageOps.fit(Image.open(p).convert("RGB"), (tw, th),
                                 Image.Resampling.LANCZOS),
                    ((i % cols) * tw, (i // cols) * th))
    sheet_path = out_dir / "final_contact_sheet.jpg"
    sheet.save(sheet_path, quality=92, subsampling=0)
    print(f"总览图: {sheet_path}")


if __name__ == "__main__":
    main()
