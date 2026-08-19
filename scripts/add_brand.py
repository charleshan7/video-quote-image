#!/usr/bin/env python3
"""给金句长图叠品牌标识：图标锚在左上角版式边距，字标锚在 footer 文字右侧。

位置一律**相对参照物**算，不写死像素：
  图标  → (margin, margin)，和标题/字幕同一条左边距
  字标  → footer 那行（"…· 2026.07.28 · 56min"）的右端 + gap，垂直居中对齐该行
换素材、改 footer 文案、改 --margin/--hero-fraction，标识会自己跟着挪。

原始 logo 是「黑线稿 + 白实底」。整体涂色会连白底一起涂，猫身和线条糊成一坨；
所以按墨色深浅转 alpha，只有黑线上色，白底透出照片。

底图是照片，深色处黑墨会断线，默认给图标垫一层白色柔光（--halo）。
"""
import argparse, json
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

LATIN = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"   # 同 render_quote_cards
# 下面两个只是兜底：正常情况下版式参数从渲染器写出的 render.json 读，
# 手抄常量会在改 --hero-fraction 后悄悄错位。
FOOTER_SIZE = 25          # render_quote_cards.hero() 里 footer 的字号
FOOTER_UP = 60            # footer 距主画面底部的距离


def ink_crop(path):
    im = Image.open(path).convert("RGBA")
    return im.crop(im.split()[3].getbbox())


def line_alpha(im):
    """「黑线稿+白实底」→ 线稿蒙版：越黑越不透明，白底转透明。"""
    return ImageChops.multiply(im.convert("L").point(lambda v: 255 - v), im.split()[3])


def stamp(base, mask, xy, color, halo, blur, spread):
    x, y = xy
    if halo > 0:
        pad = spread + int(blur) * 2
        sh = Image.new("L", (mask.width + pad * 2, mask.height + pad * 2), 0)
        sh.paste(mask, (pad, pad))
        sh = sh.filter(ImageFilter.MaxFilter(spread * 2 + 1))
        sh = sh.filter(ImageFilter.GaussianBlur(blur))
        sh = sh.point(lambda v: int(v * halo))
        back = (255, 255, 255) if color == (0, 0, 0) else (0, 0, 0)
        base.paste(Image.new("RGB", sh.size, back), (x - pad, y - pad), sh)
    base.paste(Image.new("RGB", mask.size, color), (x, y), mask)


def fit_font(target_h, text):
    """选字号让该字形的墨迹高度≈target_h（@ 的字面高和字号差很多）。"""
    size = max(6, int(target_h * 1.2))
    while size < target_h * 4:
        f = ImageFont.truetype(LATIN, size)
        bb = f.getbbox(text)
        if bb[3] - bb[1] >= target_h:
            return f, bb
        size += 1
    f = ImageFont.truetype(LATIN, size)
    return f, f.getbbox(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--logo-dir", default=None,
                    help="品牌素材目录；默认先找 ~/Developer/ffdy-brand，没有就用仓库自带 assets/brand")
    ap.add_argument("--spec", help="读 meta.footer 用于定位字标；不给就用 --footer")
    ap.add_argument("--render", help="渲染器写出的 render.json（版式真源）；"
                                     "默认自动找源图同目录的 render.json")
    ap.add_argument("--footer", default="", help="直接给 footer 文案（覆盖 --spec）")
    # 版式参照（要和渲染时一致，否则锚点算不准）
    ap.add_argument("--margin", type=int, default=None)
    ap.add_argument("--hero-fraction", type=float, default=None)
    # 图标
    ap.add_argument("--icon-h", type=int, default=96)
    ap.add_argument("--ink", choices=["white", "black"], default="black")
    ap.add_argument("--halo", type=float, default=0.9, help="白色柔光垫底，0=纯墨")
    ap.add_argument("--x", type=int, default=-1, help="覆盖图标 x，-1=用 margin")
    ap.add_argument("--y", type=int, default=-1, help="覆盖图标 y，-1=用 margin")
    # 字标
    ap.add_argument("--word-h", type=int, default=22)
    ap.add_argument("--word-gap", type=int, default=28, help="与 footer 文字的间距")
    ap.add_argument("--word-ink", choices=["white", "black"], default="white")
    ap.add_argument("--word-halo", type=float, default=0.0)
    ap.add_argument("--no-at", action="store_true")
    ap.add_argument("--word-x", type=int, default=-1, help="覆盖字标 x，-1=锚 footer 右侧")
    ap.add_argument("--word-y", type=int, default=-1, help="覆盖字标 y，-1=对齐 footer")
    ap.add_argument("--blur", type=float, default=19.8)
    ap.add_argument("--spread", type=int, default=6)
    a = ap.parse_args()

    base = Image.open(a.src).convert("RGB")

    # 版式参数一律以渲染器写出的 render.json 为准，命令行显式传的才覆盖它。
    # 两边各存一份默认值时，改了 --hero-fraction 只改渲染那侧，字标就飘了。
    rp = Path(a.render) if a.render else Path(a.src).parent / "render.json"
    R = json.load(open(rp, encoding="utf-8")) if rp.exists() else {}
    margin = a.margin if a.margin is not None else R.get("margin", 56)
    hero_frac = a.hero_fraction if a.hero_fraction is not None else R.get("hero_fraction", 0.362)
    hero_h = R.get("hero_h") or round(base.height * hero_frac)
    f_size, f_up = R.get("footer_size", FOOTER_SIZE), R.get("footer_up", FOOTER_UP)
    hero_text = R.get("hero_text", True)
    src_note = f"render.json({rp.parent.name}/)" if R else "内置默认值"
    if a.logo_dir:
        L = Path(a.logo_dir)
    else:                                   # 本机品牌目录优先，clone 下来的机器回落到仓库自带
        local = Path.home() / "Developer/ffdy-brand"
        L = local if (local / "cat-circle.webp").exists() else Path(__file__).parent.parent / "assets/brand"
    if not (L / "cat-circle.webp").exists():
        raise SystemExit(f"找不到品牌素材：{L}/cat-circle.webp（用 --logo-dir 指定）")
    RGB = {"white": (255, 255, 255), "black": (0, 0, 0)}

    # —— 图标：锚版式左边距
    icon = ink_crop(L / "cat-circle.webp")
    icon = icon.resize((round(a.icon_h * icon.width / icon.height), a.icon_h), Image.LANCZOS)
    ix = margin if a.x < 0 else a.x
    iy = margin if a.y < 0 else a.y
    stamp(base, line_alpha(icon), (ix, iy), RGB[a.ink], a.halo, a.blur, a.spread)

    # —— 字标：@ + 飞飞豆芽
    word = ink_crop(L / "wordmark.webp")
    word = word.resize((round(a.word_h * word.width / word.height), a.word_h), Image.LANCZOS)
    lock = line_alpha(word)
    if not a.no_at:
        f, bb = fit_font(a.word_h, "@")
        aw, ah = bb[2] - bb[0], bb[3] - bb[1]
        gap = max(4, round(a.word_h * 0.34))
        merged = Image.new("L", (aw + gap + lock.width, a.word_h), 0)
        ImageDraw.Draw(merged).text((-bb[0], -bb[1] + (a.word_h - ah) // 2), "@", font=f, fill=255)
        merged.paste(lock, (aw + gap, 0))
        lock = merged

    footer = a.footer
    if not footer and a.spec:
        footer = (json.load(open(a.spec, encoding="utf-8")).get("meta") or {}).get("footer", "")

    if a.word_x >= 0 and a.word_y >= 0:
        wx, wy, anchor = a.word_x, a.word_y, "手动坐标"
    elif not hero_text or not footer:
        # --no-hero-text 的版式主画面上根本没有 footer 那行，锚上去会落进字幕条里。
        # 退到主画面左下角，与图标同一条左边距。
        wx = margin if a.word_x < 0 else a.word_x
        wy = hero_h - a.word_h - margin if a.word_y < 0 else a.word_y
        anchor = "主画面无 footer 行，退到左下角"
    else:
        fy = hero_h - f_up                            # render_quote_cards 里 footer 的 y
        ff = ImageFont.truetype(LATIN, f_size)
        fb = ff.getbbox(footer)
        fw = ImageDraw.Draw(base).textlength(footer, font=ff)
        # 垂直：字标墨迹中心对齐 footer 墨迹中心
        f_top, f_bot = fy + fb[1], fy + fb[3]
        wx = margin + round(fw) + a.word_gap if a.word_x < 0 else a.word_x
        wy = round((f_top + f_bot) / 2 - a.word_h / 2) if a.word_y < 0 else a.word_y
        anchor = f"footer 右侧+{a.word_gap} 「{footer}」"

    stamp(base, lock, (wx, wy), RGB[a.word_ink], a.word_halo, a.blur, a.spread)
    base.save(a.out, quality=93, subsampling=0)
    print(f"完成: {a.out}\n  版式来源 {src_note}: margin={margin} hero_h={hero_h} "
          f"hero_text={hero_text}"
          f"\n  图标 {icon.width}x{icon.height} @({ix},{iy}) {a.ink} halo={a.halo}"
          f"\n  字标 {lock.width}x{lock.height} @({wx},{wy}) {a.word_ink}  锚点={anchor}")


if __name__ == "__main__":
    main()
