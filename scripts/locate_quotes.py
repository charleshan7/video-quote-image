#!/usr/bin/env python3
"""在字幕文件里定位每句金句的真实时间点，把 quotes.json 编译成渲染用的 spec.json。

用途：视频画面里没有烧录字幕时，金句文字来自字幕轨，时间点必须回字幕里查，
不能手填——手填的时间戳跟画面对不上，读者跳回原片会扑空。
"""
import argparse
import json
import re
import sys

CUE = re.compile(
    r"(\d{1,2}:\d\d:\d\d[,.]\d+)\s*-->\s*[\d:,.]+\s*\n(.*?)(?=\n\s*\n|\Z)", re.S)


def secs(ts):
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def load_cues(path):
    """SRT / VTT 都能读；返回 [(秒, 小写文本)]。"""
    raw = open(path, encoding="utf-8-sig").read()
    cues = []
    for ts, text in CUE.findall(raw):
        line = " ".join(re.sub(r"<[^>]+>", "", text).split())
        if line:
            cues.append((secs(ts), line.lower()))
    if not cues:
        sys.exit(f"没从 {path} 解析出任何字幕行")
    return cues


def build_index(cues):
    """拼成一条长文本，并记录每个字符位置对应的时间，便于跨行匹配。"""
    parts, index = [], []
    for t, line in cues:
        parts.append(line)
        index.extend([t] * (len(line) + 1))
    return " ".join(parts), index


def find_time(flat, index, phrase, after=0.0):
    needle = " ".join(phrase.lower().split())
    pos = 0
    while True:
        pos = flat.find(needle, pos)
        if pos == -1:
            return None
        t = index[min(pos, len(index) - 1)]
        if t >= after:
            return t
        pos += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subtitles", help="SRT 或 VTT 文件")
    ap.add_argument("quotes", help="人工挑好的金句表 quotes.json")
    ap.add_argument("-o", "--out", default="spec.json")
    ap.add_argument("--settle", type=float, default=1.2,
                    help="命中后往后挪多少秒取帧，避开句子刚出现的瞬间（默认 1.2）")
    args = ap.parse_args()

    cues = load_cues(args.subtitles)
    flat, index = build_index(cues)
    doc = json.load(open(args.quotes, encoding="utf-8"))

    spec = {"meta": doc.get("meta", {}), "images": []}
    missing = []
    for image in doc["images"]:
        items, cursor = [], 0.0
        for q in image["quotes"]:
            t = find_time(flat, index, q["match"], after=cursor)
            if t is None:                      # 允许倒着引用，退回全局搜
                t = find_time(flat, index, q["match"])
            if t is None:
                missing.append((image["title"], q["match"]))
                continue
            entry = {"time": round(t + args.settle, 2),
                     "cn": q.get("cn", ""), "en": q.get("en", "")}
            if "frame_time" in q:      # 指定画面帧，时间码仍用这句话的真实位置
                entry["frame_time"] = q["frame_time"]
            items.append(entry)
            cursor = t
        if not items:
            sys.exit(f"「{image['title']}」一句都没定位到，检查 match 短语是否照抄字幕原文")
        items.sort(key=lambda i: i["time"])    # 同图内按时间排序，保证是连续表达
        for prev, cur in zip(items, items[1:]):
            # 两句落在同一条字幕上时时间点会撞车，取到的帧和时间码都会重复
            if cur["time"] - prev["time"] < 1.5:
                cur["time"] = round(prev["time"] + 1.5, 2)
        spec["images"].append({
            "title": image["title"],
            "hero_time": image.get("hero_time", items[0]["time"]),
            "quotes": items,
        })
        stamps = ", ".join(f"{int(i['time'])//60:02d}:{int(i['time'])%60:02d}"
                           for i in items)
        print(f"{image['title']}: {len(items)} 句 [{stamps}]")

    if missing:
        print("\n以下短语没在字幕里找到（必须照抄字幕原文，含缩写和标点差异）：",
              file=sys.stderr)
        for title, phrase in missing:
            print(f"  {title} → {phrase!r}", file=sys.stderr)

    json.dump(spec, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
