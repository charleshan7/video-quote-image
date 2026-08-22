#!/usr/bin/env python3
"""Locate selected quotes in SRT/WebVTT without inventing source timestamps."""
from __future__ import annotations

import argparse
import html
import json
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TIMING = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d+)\s*-->\s*"
    r"(?P<end>(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d+)(?:\s+.*)?$"
)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, secs = parts
    elif len(parts) == 3:
        hours, minutes, secs = parts
    else:
        raise ValueError(f"invalid subtitle timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def normalize_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    value = unicodedata.normalize("NFKC", value).lower().replace("’", "'")
    return " ".join(re.sub(r"[^\w']+", " ", value, flags=re.UNICODE).split())


def load_cues(path: str | Path) -> list[Cue]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="strict").replace("\r\n", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [line.strip("\ufeff") for line in block.splitlines()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = TIMING.fullmatch(lines[timing_index].strip())
        if not match:
            continue
        text = normalize_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        start, end = seconds(match.group("start")), seconds(match.group("end"))
        if end <= start:
            raise SystemExit(f"字幕 cue 结束时间不大于开始时间：{lines[timing_index]}")
        cues.append(Cue(start=start, end=end, text=text))
    if not cues:
        raise SystemExit(f"没从 {path} 解析出任何 SRT/WebVTT 字幕行")
    return cues


def build_index(cues: list[Cue]) -> tuple[str, list[Cue]]:
    parts: list[str] = []
    index: list[Cue] = []
    for cue in cues:
        if parts:
            index.append(cue)
        parts.append(cue.text)
        index.extend([cue] * len(cue.text))
    return " ".join(parts), index


def find_cue(flat: str, index: list[Cue], phrase: str, after: float = 0.0) -> Cue | None:
    needle = normalize_text(phrase)
    if not needle:
        return None
    position = 0
    while True:
        position = flat.find(needle, position)
        if position < 0:
            return None
        cue = index[min(position, len(index) - 1)]
        if cue.start >= after:
            return cue
        position += 1


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subtitles", help="SRT 或 WebVTT 文件")
    ap.add_argument("quotes", help="人工挑好的 quotes.json")
    ap.add_argument("-o", "--out", default="spec.json")
    ap.add_argument(
        "--settle", type=float, default=0.0,
        help="显式从 cue 开始时间后移秒数；默认 0，不改变来源时间",
    )
    args = ap.parse_args()
    if args.settle < 0:
        raise SystemExit("--settle 不能为负数")

    cues = load_cues(args.subtitles)
    flat, index = build_index(cues)
    doc = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    if not isinstance(doc.get("images"), list) or not doc["images"]:
        raise SystemExit("quotes.json 的 images 不能为空")

    spec = {"meta": doc.get("meta", {}), "images": []}
    missing: list[tuple[str, str]] = []
    for image_index, image in enumerate(doc["images"], 1):
        if not image.get("quotes"):
            raise SystemExit(f"第 {image_index} 组没有 quotes")
        items = []
        image_missing = False
        cursor = 0.0
        for quote_index, quote in enumerate(image["quotes"], 1):
            phrase = str(quote.get("match", ""))
            cue = find_cue(flat, index, phrase, after=cursor) or find_cue(flat, index, phrase)
            if cue is None:
                missing.append((str(image.get("title", image_index)), phrase))
                image_missing = True
                continue
            timestamp = min(cue.end, cue.start + args.settle)
            entry = dict(quote)
            entry.update({
                "quote_id": str(quote.get("quote_id") or f"img{image_index:02d}-q{quote_index:02d}"),
                "time": round(timestamp, 3),
                "cue_start": round(cue.start, 3),
                "cue_end": round(cue.end, 3),
                "time_basis": "cue_start" if args.settle == 0 else f"cue_start+{args.settle:g}s",
                "match": phrase,
                "source_en": quote.get("source_en", phrase),
                "en": quote.get("en", phrase),
                "cn": quote.get("cn", ""),
            })
            items.append(entry)
            cursor = cue.start

        if image_missing:
            continue
        items.sort(key=lambda item: (item["time"], item["quote_id"]))
        compiled = dict(image)
        compiled["id"] = str(image.get("id") or f"img{image_index:02d}")
        compiled["quotes"] = items
        if "hero_time" not in compiled:
            compiled["hero_time"] = items[0]["time"]
            compiled["hero_time_basis"] = "first_quote_fallback_requires_review"
        spec["images"].append(compiled)
        stamps = ", ".join(f"{int(item['time'])//60:02d}:{int(item['time'])%60:02d}" for item in items)
        print(f"{compiled.get('title', compiled['id'])}: {len(items)} 句 [{stamps}]")

    if missing:
        lines = ["以下短语没在字幕里找到；未写出任何 spec："]
        lines.extend(f"  {title} → {phrase!r}" for title, phrase in missing)
        raise SystemExit("\n".join(lines))

    out = Path(args.out)
    atomic_write_json(out, spec)
    print(f"→ {out}")


if __name__ == "__main__":
    main()
