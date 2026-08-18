#!/usr/bin/env python3
"""ASR 交叉校验：用第二家语音识别复核入选金句的英文原文。

为什么需要：字幕多半是平台自动生成的（YouTube 等），本身就带语音识别错误。
翻译校验只能间接推断"这个词在这儿不合理"，听错成另一个合法词（人名、数字、
专有名词）就抓不出来。图上带时间码，读者真去核对时，错在英文这层比翻译错更难解释。

不绑定任何厂商：脚本只负责「切片 → 调用 → 比对」，中间那步用 --asr-cmd 传任意引擎的命令；
不传就切完停下，把 wav 和期望的输出文件名列出来，用 API、MCP 工具、网页版填进去都行。

    # 一步到位（本机已装 whisper.cpp）
    asr_crosscheck.py VIDEO --spec spec.json --subs SUBS.srt --out-dir asr-xcheck \
      --asr-cmd 'whisper-cli -m ~/.cache/whisper-cpp/ggml-large-v3-turbo-q5_0.bin \
                 -f {wav} -l en -otxt -of {stem} -np'

    # 或者分两步，中间用任意引擎
    asr_crosscheck.py VIDEO --spec spec.json --subs SUBS.srt --out-dir asr-xcheck
    ...（自己把每个 {stem}.txt 写出来）...
    asr_crosscheck.py VIDEO --spec spec.json --subs SUBS.srt --out-dir asr-xcheck --diff-only
"""
import argparse, difflib, json, os, re, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from locate_quotes import load_cues                      # 复用字幕解析，保持口径一致

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = shutil.which("ffmpeg") or sys.exit("找不到 ffmpeg")

NEG = {"not", "no", "never", "none", "nothing", "nobody", "cannot", "cant", "dont",
       "doesnt", "didnt", "wont", "wouldnt", "shouldnt", "isnt", "arent", "wasnt"}
FILLER = {"uh", "um", "uhh", "umm", "mm", "mhm", "hmm", "ah", "oh", "er", "eh"}


def norm(text):
    return re.sub(r"[^\w\s']", " ", text.lower()).split()


def srt_window(cues, t0, t1):
    """取 [t0,t1] 覆盖到的字幕原文。"""
    return " ".join(line for t, line in cues if t0 <= t <= t1)


def has_audio(video):
    """yt-dlp 下的高码率 DASH 视频流是纯画面，没有音轨——必须先拦住，否则每段都失败。"""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(video)],
                       capture_output=True, text=True)
    return "Audio:" in r.stderr


def cut(video, t0, dur, wav):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{t0:.2f}", "-i", str(video), "-t", f"{dur:.2f}",
                    "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                   check=True, capture_output=True)


def align(rt, at):
    """把 ASR 文本截到与字幕对齐的那一段。

    音频比字幕窗口切得宽（给 ASR 留上下文），直接整段对整段 diff，
    头尾多出来的词会全被报成分歧——实测 36 段能刷出 78 处假阳性，报告直接废掉。
    """
    blocks = [b for b in difflib.SequenceMatcher(None, rt, at).get_matching_blocks() if b.size]
    if not blocks:
        return at
    head, tail = blocks[0], blocks[-1]
    j0 = head.b - head.a                                   # ASR 起点回退到字幕第一个词
    j1 = tail.b + tail.size + (len(rt) - tail.a - tail.size)
    return at[max(0, j0):max(0, j1)]


def classify(srt_tok, asr_tok, proper):
    """分级：改变意思的优先看，语气词噪声压到最后。"""
    both = set(srt_tok) | set(asr_tok)
    if both & NEG:
        return "高", "否定词不一致"
    if any(any(c.isdigit() for c in w) for w in both):
        return "高", "数字不一致"
    if both & proper:
        return "高", "专有名词/人名不一致"
    if both <= FILLER:
        return "低", "语气词"
    return "中", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--spec", required=True, help="定稿的 spec.json，只校验入选的句子")
    ap.add_argument("--subs", required=True, help="原字幕 SRT/VTT，作为被校验的一方")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--pad", type=float, default=3.0, help="比对窗口：每句前后各取几秒的字幕")
    ap.add_argument("--context", type=float, default=4.0,
                    help="额外多切给 ASR 当上下文的秒数。必须 >0：音频窗口要是比字幕窗口窄，"
                         "字幕会带进整条 cue 的尾巴而音频已经切断，系统性产生假阳性")
    ap.add_argument("--asr-cmd", help="第二家 ASR 的命令模板，占位符 {wav} {stem}")
    ap.add_argument("--diff-only", action="store_true", help="跳过切片和识别，只比对")
    ap.add_argument("--report", default="asr-xcheck.md")
    a = ap.parse_args()

    if not a.diff_only and not has_audio(a.video):
        sys.exit(f"{a.video} 没有音轨（yt-dlp 的 DASH 视频流常见）。"
                 f"换成带声音的那份，或先 ffmpeg 合流。")

    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    cues = load_cues(a.subs)
    spec = json.load(open(a.spec, encoding="utf-8"))

    segs = []
    for i, image in enumerate(spec["images"], 1):
        for j, q in enumerate(image["quotes"], 1):
            t = q["time"]
            segs.append({"id": f"{i:02d}-{j:02d}", "img": image["title"], "t": t,
                         "t0": max(0.0, t - a.pad), "dur": a.pad * 2,
                         "a0": max(0.0, t - a.pad - a.context),
                         "adur": (a.pad + a.context) * 2,
                         "cn": q.get("cn", ""), "en": q.get("en", "")})

    for s in segs:
        s["wav"] = out / f"{s['id']}.wav"
        s["txt"] = out / f"{s['id']}.txt"
        if not a.diff_only:
            cut(a.video, s["a0"], s["adur"], s["wav"])

    if not a.diff_only and a.asr_cmd:
        for n, s in enumerate(segs, 1):
            cmd = a.asr_cmd.replace("{wav}", str(s["wav"])).replace("{stem}", str(out / s["id"]))
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if not s["txt"].exists() and r.stdout.strip():   # 引擎只吐 stdout 时兜住
                s["txt"].write_text(r.stdout, encoding="utf-8")
            print(f"\r识别 {n}/{len(segs)}", end="", flush=True)
        print()
    elif not a.diff_only:
        print(f"已切出 {len(segs)} 段到 {out}/。用任意 ASR 把每段转成同名 .txt，再加 --diff-only 重跑：")
        for s in segs[:3]:
            print(f"  {s['wav'].name} → {s['txt'].name}")
        print("  …")
        return

    rows, missing, low = [], 0, 0
    for s in segs:
        if not s["txt"].exists():
            missing += 1
            continue
        asr = s["txt"].read_text(encoding="utf-8")
        ref = srt_window(cues, s["t0"], s["t0"] + s["dur"])
        rt, at = norm(ref), norm(asr)
        at = align(rt, at)          # ASR 覆盖面更宽，先截到和字幕对齐的那一段
        proper = {w.lower() for w in re.findall(r"\b[A-Z][a-z]{2,}\b", ref)}
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, rt, at).get_opcodes():
            if tag == "equal":
                continue
            if i1 == 0 or i2 >= len(rt):
                continue            # 贴着窗口边界的分歧一律不算，那里两边覆盖面本就不同
            a_side, b_side = rt[i1:i2], at[j1:j2]
            lvl, why = classify(a_side, b_side, proper)
            if lvl == "低":
                low += 1
                continue
            rows.append({"id": s["id"], "img": s["img"], "t": s["t"], "lvl": lvl, "why": why,
                         "srt": " ".join(a_side) or "（无）", "asr": " ".join(b_side) or "（无）",
                         "ctx": " ".join(rt[max(0, i1 - 6):i2 + 6]), "en": s["en"], "cn": s["cn"]})

    rows.sort(key=lambda r: (r["lvl"] != "高", r["id"]))
    hi = sum(1 for r in rows if r["lvl"] == "高")
    lines = [f"# ASR 交叉校验\n",
             f"字幕 `{Path(a.subs).name}` vs 第二家识别，共 {len(segs)} 段，"
             f"分歧 {len(rows)} 处（高 {hi}），语气词噪声 {low} 处已滤除。"
             + (f"\n\n⚠️ {missing} 段没拿到识别结果。" if missing else "") + "\n",
             "**高 = 否定词/数字/专有名词不一致，会改变意思，必须回原音频听。**\n"]
    for r in rows:
        lines += [f"\n## [{r['lvl']}] {r['id']} · {r['img']} · {int(r['t'])//60:02d}:{int(r['t'])%60:02d}"
                  + (f" — {r['why']}" if r["why"] else ""),
                  f"- 字幕: `{r['srt']}`",
                  f"- 二次识别: `{r['asr']}`",
                  f"- 上下文: …{r['ctx']}…",
                  f"- 图上英文: {r['en']}",
                  f"- 图上中文: {r['cn']}"]
    Path(a.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {a.report}：{len(segs)} 段，分歧 {len(rows)} 处（高 {hi}），噪声滤除 {low} 处")


main()
