#!/usr/bin/env python3
"""Preflight gate for video-quote-image deliveries.

Usage:
  python preflight.py --root PROJECT --video VIDEO --status reviewed
  python preflight.py --root PROJECT --video VIDEO --status final

All paths other than --video are relative to --root. The script writes
preflight_report.json and preflight_report.md unless --no-report is passed.
Exit 0 means the requested status is allowed; non-zero blocks delivery.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from media_tools import ffmpeg_exe, ffprobe_exe

CN_RE = re.compile(r"[\u3400-\u9fff]")
REQUIRED_PEOPLE = ["name", "person_type", "role", "source_url", "source_quote", "verified_at", "confidence"]
REQUIRED_PACKAGE_TERMS = ["人物介绍", "首发标题", "封面大字", "轮播顺序", "评论区引导", "话题标签"]
RISK_TRIGGERS = {"politics", "war", "religion", "medical", "legal", "finance", "minors", "numbers", "proper_nouns", "strong_claims"}
RISK_TERM_MAP = {
    "politics": ["politic", "government", "policy", "政治", "政府"],
    "war": ["war", "anti-war", "russia", "战争", "反战"],
    "religion": ["islam", "muslim", "christian", "jesus", "church", "christianity", "宗教", "伊斯兰", "基督"],
    "medical": ["medical", "medicine", "health", "医疗", "医学"],
    "legal": ["law", "legal", "court", "法律", "法院"],
    "finance": ["finance", "financial", "invest", "money", "金融", "投资"],
    "minors": ["minor", "child", "children", "未成年人", "儿童"],
    "numbers": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
    "strong_claims": ["always", "never", "must", "all", "none", "proves", "guaranteed", "绝对", "必然", "所有", "永远", "证明"],
}


ASR_FAMILIES = {
    "whisper": ("whisper",),
    "elevenlabs-scribe": ("scribe", "elevenlabs"),
    "google-asr": ("google", "youtube-auto", "youtube auto"),
    "deepgram": ("deepgram",),
    "assemblyai": ("assemblyai",),
}


def asr_family(engine: str) -> str:
    """Collapse an engine name to its architecture family.

    openai-whisper, whisper.cpp and faster-whisper share an encoder, so pairing
    them is not a second opinion — they fail together on the same word.
    """
    name = engine.strip().lower()
    for family, markers in ASR_FAMILIES.items():
        if any(marker in name for marker in markers):
            return family
    return name


def load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    if not path.exists():
        errors.append(f"missing {label}: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid JSON {label}: {exc}")
        return None


def rel(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def probe_video(video: Path, errors: list[str], warnings: list[str]) -> dict[str, Any] | None:
    if not video.exists():
        errors.append(f"missing source video: {video}")
        return None
    cmd = [ffprobe_exe(), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,sample_rate,channels", "-of", "json", str(video)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except Exception as exc:
        errors.append(f"ffprobe failed: {exc}")
        return None
    streams = data.get("streams", [])
    types = {s.get("codec_type") for s in streams}
    if "video" not in types:
        errors.append("source has no video stream")
    if "audio" not in types:
        errors.append("source has no audio stream; translation gate cannot pass")
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        errors.append("source duration is missing or non-positive")
    if duration < 30:
        warnings.append(f"source duration is unusually short: {duration:.3f}s")
    return {"duration": duration, "streams": streams, "types": sorted(x for x in types if x)}


def parse_srt_text(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8", errors="replace").lower()
    blocks = re.split(r"\n\s*\n", raw)
    cues: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            cues.append(" ".join(" ".join(lines[2:]).split()))
    return " ".join(cues)


def check_spec(spec: dict[str, Any], selection: dict[str, Any] | None, quotes_file: dict[str, Any] | None, duration: float, subs_text: str, errors: list[str], warnings: list[str], passes: list[str]) -> None:
    images = spec.get("images") if isinstance(spec, dict) else None
    if not isinstance(images, list) or not 4 <= len(images) <= 6:
        errors.append("spec.images must contain 4–6 image groups")
        return
    if selection and len(selection.get("images", [])) != len(images):
        errors.append("spec/selection_audit image count mismatch")
    actual_counts = []
    all_quote_ids: list[str] = []
    for index, image in enumerate(images, 1):
        title = image.get("title", f"image {index}")
        quotes = image.get("quotes", [])
        actual_counts.append(len(quotes))
        required_image = ["id", "title", "hero_time", "hero_subject", "hero_subject_role", "hero_subject_source_url", "hero_subject_source_quote", "hero_subject_confidence", "hero_audit", "structure", "core_quote_index"]
        for key in required_image:
            if key not in image:
                errors.append(f"{title}: missing spec field {key}")
        if image.get("hero_subject_role") not in {"interviewer", "speaker"}:
            errors.append(f"{title}: hero_subject_role must be interviewer or speaker")
        if duration and float(image.get("hero_time", 0)) > duration:
            errors.append(f"{title}: hero_time exceeds source duration")
        if not quotes or len(quotes) > 8:
            errors.append(f"{title}: quote count must be 1–8 and is {len(quotes)}")
        core = image.get("core_quote_index")
        if not isinstance(core, int) or core < 0 or core >= len(quotes):
            errors.append(f"{title}: invalid core_quote_index")
        if selection:
            audit = next((x for x in selection.get("images", []) if str(x.get("id")) == str(image.get("id"))), None)
            if audit is None:
                errors.append(f"{title}: missing matching selection audit record")
            else:
                for key in ["structure", "planned_count", "actual_count", "core_quote_index", "rejected_quotes", "count_reason"]:
                    if key not in audit:
                        errors.append(f"{title}: selection audit missing {key}")
                if audit.get("planned_count") != len(quotes) or audit.get("actual_count") != len(quotes):
                    errors.append(f"{title}: planned/actual count mismatch")
        times = []
        seen_cn: set[str] = set()
        for qi, q in enumerate(quotes, 1):
            prefix = f"{title} q{qi}"
            for key in ["quote_id", "time", "frame_time", "match", "source_en", "en", "cn"]:
                if key not in q:
                    errors.append(f"{prefix}: missing quote field {key}")
            try:
                time = float(q.get("time", -1))
                frame_time = float(q.get("frame_time", -1))
                times.append(time)
            except Exception:
                errors.append(f"{prefix}: invalid time/frame_time")
                continue
            if not (0 <= time <= duration):
                errors.append(f"{prefix}: time outside source duration")
            if abs(frame_time - time) < 0.01:
                errors.append(f"{prefix}: frame_time must be independently selected and differ from time")
            if not (0 <= frame_time <= duration):
                errors.append(f"{prefix}: frame_time outside source duration")
            quote_id = str(q.get("quote_id", "")).strip()
            if quote_id in all_quote_ids:
                errors.append(f"{prefix}: duplicate quote_id {quote_id}")
            all_quote_ids.append(quote_id)
            cn_len = len(CN_RE.findall(str(q.get("cn", ""))))
            if not 10 <= cn_len <= 16:
                errors.append(f"{prefix}: Chinese length {cn_len} outside 10–16")
            en_len = len(str(q.get("en", "")))
            if en_len > 65:
                errors.append(f"{prefix}: English length {en_len} exceeds 65")
            if q.get("source_en") != q.get("match"):
                errors.append(f"{prefix}: source_en must equal match")
            if q.get("cn") in seen_cn:
                errors.append(f"{prefix}: duplicated Chinese quote")
            seen_cn.add(q.get("cn"))
            if subs_text and " ".join(str(q.get("match", "")).lower().split()) not in subs_text:
                errors.append(f"{prefix}: match not found in supplied SRT")
        if times != sorted(times):
            errors.append(f"{title}: quote times are not sorted")
    if len(set(actual_counts)) == 1:
        warnings.append("all image groups use the same quote count; prove structure-specific reasons or revise")
    passes.append(f"spec and selection structure checked: {actual_counts}")


def check_translation(root: Path, audit: dict[str, Any] | None, spec: dict[str, Any] | None, asr_report: Path, status: str, errors: list[str], warnings: list[str], passes: list[str]) -> None:
    """Require four complete, quote-level calibration rounds for every delivered status.

    `reviewed` and `final` require complete quote-level calibration artifacts and
    may not pass with missing rounds, completed_with_limitations, or narrative-only audits.
    `final` additionally requires heterogeneous ASR evidence.
    """
    if audit is None:
        return
    if status == "draft":
        warnings.append("draft status skips the four-round delivery gate")
        return
    expected = sum(len(image.get("quotes", [])) for image in (spec or {}).get("images", []))
    rounds = {int(item.get("round")): item for item in audit.get("rounds", []) if str(item.get("round", "")).isdigit()}
    if set(rounds) != {0, 1, 2, 3}:
        errors.append("translation audit must contain rounds 0, 1, 2 and 3")
    default_artifacts = {
        0: "audit/review_asr_xcheck.json",
        1: "audit/round1_self_check.json",
        2: "audit/round2_mechanical_diff.json",
        3: "audit/round3_adjudication.json",
    }
    expected_ids = {str(q.get("quote_id")) for image in (spec or {}).get("images", []) for q in image.get("quotes", [])}
    required_fields = {
        0: ["quote_id", "source_en", "second_source", "severity"],
        1: ["quote_id", "source_en", "current_cn", "checks", "adjudication"],
        2: ["quote_id", "source_en", "current_cn", "diff", "changed"],
        3: ["quote_id", "source_en", "current_cn", "claims", "evidence_basis", "adjudication", "changed"],
    }
    for number in range(4):
        record = rounds.get(number)
        if not record:
            continue
        if record.get("status") != "completed":
            errors.append(f"translation round {number} status must be completed, got {record.get('status')}")
        artifact_value = record.get("artifact", default_artifacts[number])
        artifact = rel(root, artifact_value)
        if not artifact.exists():
            errors.append(f"translation round {number} missing artifact: {artifact_value}")
            continue
        try:
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"translation round {number} artifact is not valid JSON: {exc}")
            continue
        rows = data.get("rows", data.get("quotes", [])) if isinstance(data, dict) else []
        if not isinstance(rows, list) or len(rows) != expected:
            errors.append(f"translation round {number} rows {len(rows) if isinstance(rows, list) else 0} != quote count {expected}")
            continue
        row_ids = []
        for row_index, row in enumerate(rows, 1):
            for field in required_fields[number]:
                if field not in row:
                    errors.append(f"translation round {number} row {row_index} missing {field}")
            row_ids.append(str(row.get("quote_id", "")))
        if set(row_ids) != expected_ids or len(row_ids) != len(set(row_ids)):
            errors.append(f"translation round {number} quote_id set does not match spec")
        passes.append(f"translation round {number} complete: {len(rows)} quote rows")
    if not asr_report.exists():
        errors.append("missing quote-level ASR report")
    primary_engine = str(audit.get("primary_source_engine") or "").strip()
    second_engine = str(audit.get("second_source_engine") or "").strip()
    declared = audit.get("independent_architecture")
    if declared is False:
        warnings.append("second ASR is explicitly same architecture/family")
    if status == "final":
        # Fail closed: silence is not evidence. The engines must be named, and the
        # family comparison is derived from those names so a wrong self-declaration
        # cannot pass the gate on its own.
        if declared is not True:
            errors.append("final status requires translation_audit.independent_architecture=true")
        for field, value in (("primary_source_engine", primary_engine), ("second_source_engine", second_engine)):
            if not value:
                errors.append(f"final status requires translation_audit.{field}")
        if primary_engine and second_engine and asr_family(primary_engine) == asr_family(second_engine):
            errors.append(
                f"primary and second ASR share the {asr_family(primary_engine)} family: "
                f"{primary_engine} / {second_engine}"
            )
    if not errors:
        passes.append("four-round calibration gate satisfied")


def check_people(people: dict[str, Any] | None, spec: dict[str, Any] | None, errors: list[str], passes: list[str]) -> None:
    if not people or not isinstance(people.get("people"), list) or len(people["people"]) < 1:
        errors.append("people.json must contain at least one verified person")
        return
    for person in people["people"]:
        for key in REQUIRED_PEOPLE:
            if not person.get(key):
                errors.append(f"people record {person.get('name')}: missing {key}")
    allowed_hero_names = {str(image.get("hero_subject")) for image in (spec or {}).get("images", [])}
    records = {str(p.get("name")): p for p in people["people"]}
    for name in allowed_hero_names:
        record = records.get(name)
        if record is None:
            errors.append(f"hero subject missing from people.json: {name}")
        elif record.get("person_type") not in {"interviewer", "speaker"}:
            errors.append(f"hero subject {name} must be interviewer or speaker in people.json")
    if any(p.get("person_type") == "interviewer" for p in people["people"]) or any(p.get("person_type") == "speaker" for p in people["people"]):
        passes.append("people records contain an eligible interviewer/speaker hero")


def check_images(root: Path, image_dir: Path, render: Path, errors: list[str], passes: list[str]) -> None:
    if not image_dir.exists():
        errors.append(f"missing image directory: {image_dir}")
        return
    from PIL import Image
    images = sorted(image_dir.glob("0*.jpg"))
    if len(images) < 4 or len(images) > 6:
        errors.append(f"final image count must be 4–6, found {len(images)}")
    for path in images:
        try:
            if Image.open(path).size != (1440, 1920):
                errors.append(f"{path.name}: expected 1440x1920")
        except Exception as exc:
            errors.append(f"cannot read {path}: {exc}")
    render_data = load_json(render, errors, "render metadata")
    if render_data:
        if render_data.get("width") != 1440 or render_data.get("height") != 1920:
            errors.append("render.json dimensions must be 1440x1920")
        for warning in render_data.get("warnings", []):
            errors.append(f"renderer warning blocks delivery: {warning}")
    passes.append(f"image dimensions/count/render warnings checked: {len(images)}")


def check_frame_audit(frame_audit: Path, spec: dict[str, Any] | None, errors: list[str], passes: list[str]) -> None:
    data = load_json(frame_audit, errors, "frame audit")
    if not data or not spec:
        return
    hero_rows = data.get("heroes", [])
    expected_hero_ids = {str(image.get("id")) for image in spec.get("images", [])}
    actual_hero_ids = {str(row.get("image_id")) for row in hero_rows}
    if actual_hero_ids != expected_hero_ids:
        errors.append("hero frame audit image_id set does not match spec")
    for row in hero_rows:
        if row.get("hero_subject_role") not in {"interviewer", "speaker"}:
            errors.append(f"hero {row.get('image_id')}: role must be interviewer or speaker")
        if not row.get("hero_subject") or not row.get("chosen_hero_time"):
            errors.append(f"hero {row.get('image_id')}: missing subject or chosen_hero_time")
        if len(row.get("candidates", [])) < 8:
            errors.append(f"hero {row.get('image_id')}: fewer than 8 wide-window candidates")
    expected = sum(len(i.get("quotes", [])) for i in spec.get("images", []))
    expected_ids = {str(q.get("quote_id")) for image in spec.get("images", []) for q in image.get("quotes", [])}
    rows = [row for image in data.get("images", []) for row in image.get("rows", [])]
    if len(rows) != expected:
        errors.append(f"frame audit rows {len(rows)} != quote count {expected}")
    frame_ids = []
    for row in rows:
        if not row.get("quote_id"):
            errors.append(f"frame audit q{row.get('quote_index')}: missing quote_id")
        frame_ids.append(str(row.get("quote_id", "")))
        if len(row.get("candidates", [])) < 5:
            errors.append(f"frame audit q{row.get('quote_index')}: fewer than 5 candidates")
        if "chosen_frame_time" not in row:
            errors.append(f"frame audit q{row.get('quote_index')}: missing chosen_frame_time")
    if set(frame_ids) != expected_ids or len(frame_ids) != len(set(frame_ids)):
        errors.append("frame audit quote_id set does not match spec")
    passes.append(f"frame audit checked: {len(rows)} quotes")


def check_package(package: Path, errors: list[str], passes: list[str]) -> None:
    if not package.exists():
        errors.append(f"missing package file: {package}")
        return
    text = package.read_text(encoding="utf-8", errors="replace")
    for term in REQUIRED_PACKAGE_TERMS:
        if term not in text:
            errors.append(f"package missing section: {term}")
    for term in ["image_id", "quote_ids", "淘汰原因"]:
        if term not in text:
            errors.append(f"package missing traceability field: {term}")
    passes.append("publication package sections and traceability checked")


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_release_manifest(root: Path, manifest: Path, spec: dict[str, Any] | None, status: str, errors: list[str], passes: list[str]) -> None:
    data = load_json(manifest, errors, "release manifest")
    if not data or status == "draft":
        return
    required = ["version", "status", "image_count", "quote_count", "artifact_hashes", "release_zip"]
    for key in required:
        if key not in data:
            errors.append(f"release manifest missing {key}")
    if data.get("status") != status:
        errors.append(f"release manifest status {data.get('status')} != requested {status}")
    expected_images = len((spec or {}).get("images", []))
    expected_quotes = sum(len(i.get("quotes", [])) for i in (spec or {}).get("images", []))
    if data.get("image_count") != expected_images:
        errors.append("release manifest image_count mismatch")
    if data.get("quote_count") != expected_quotes:
        errors.append("release manifest quote_count mismatch")
    release_zip = rel(root, str(data.get("release_zip", "")))
    if not release_zip.exists():
        errors.append(f"release manifest ZIP missing: {data.get('release_zip')}")
    branded = sorted((root / "branded").glob("0*.jpg"))
    if branded and not all(str(p.relative_to(root)) in data.get("artifact_hashes", {}) for p in branded):
        errors.append("release manifest missing one or more branded image hashes")
    for rel_path, expected_hash in data.get("artifact_hashes", {}).items():
        artifact = rel(root, rel_path)
        if not artifact.exists():
            errors.append(f"release manifest artifact missing: {rel_path}")
        elif sha256_file(artifact) != expected_hash:
            errors.append(f"release manifest hash mismatch: {rel_path}")
    passes.append("release integration manifest and artifact hashes checked")


def check_red_team(root: Path, spec: dict[str, Any] | None, red_team: Path, status: str, errors: list[str], passes: list[str]) -> None:
    if status == "draft" or not spec:
        return
    meta = spec.get("meta") or {}
    explicit = set(meta.get("risk_flags", [])) & RISK_TRIGGERS
    quote_text = []
    for image in spec.get("images", []):
        quote_text.append(str(image.get("title", "")))
        for quote in image.get("quotes", []):
            quote_text.extend([str(quote.get("match", "")), str(quote.get("source_en", "")), str(quote.get("en", "")), str(quote.get("cn", ""))])
    haystack = " ".join(quote_text).lower()
    def contains(term: str) -> bool:
        term = term.lower()
        if any(ord(ch) > 127 for ch in term) or term.isdigit() or "-" in term:
            return term in haystack
        return re.search(r"\b" + re.escape(term) + r"\b", haystack) is not None
    detected = {flag for flag, terms in RISK_TERM_MAP.items() if any(contains(term) for term in terms)}
    if detected - explicit:
        errors.append(f"spec.meta.risk_flags missing detected triggers: {sorted(detected - explicit)}")
    active = explicit | detected
    if not active:
        passes.append("no high-risk red-team trigger active")
        return
    data = load_json(red_team, errors, "red-team audit")
    if not data:
        return
    expected = sum(len(i.get("quotes", [])) for i in spec.get("images", []))
    expected_ids = {str(q.get("quote_id")) for image in spec.get("images", []) for q in image.get("quotes", [])}
    rows = data.get("rows", [])
    if data.get("status") != "completed":
        errors.append("red-team audit status must be completed")
    if len(rows) != expected:
        errors.append(f"red-team rows {len(rows)} != quote count {expected}")
    red_ids = []
    for index, row in enumerate(rows, 1):
        red_ids.append(str(row.get("quote_id", "")))
        for field in ["quote_id", "risk_tags", "challenge", "decision"]:
            if field not in row:
                errors.append(f"red-team row {index} missing {field}")
        if row.get("decision") not in ("retain", "revise", "stop"):
            errors.append(f"red-team row {index} decision must be retain/revise/stop")
    if set(red_ids) != expected_ids or len(red_ids) != len(set(red_ids)):
        errors.append("red-team quote_id set does not match spec")
    passes.append(f"red-team audit checked for triggers: {sorted(active)}")


def check_download_manifest(root: Path, video: Path, manifest: Path, errors: list[str], passes: list[str]) -> None:
    data = load_json(manifest, errors, "source download manifest")
    if not data:
        return
    if data.get("download_mode") != "direct":
        errors.append("source download must be direct, not a preview or screenshot")
    if data.get("quality_rank") != "best_available" or data.get("is_best_available") is not True:
        errors.append("source download must be the best available quality")
    if data.get("format_selector") != "bestvideo*+bestaudio/best":
        errors.append("source download manifest must record bestvideo*+bestaudio/best selector")
    media = rel(root, str(data.get("media_path", "")))
    if not media.exists():
        errors.append(f"source download media missing: {media}")
    if media.resolve() != video.resolve():
        errors.append("source download manifest media_path does not match preflight video")
    if media.exists() and data.get("file_sha256") != sha256_file(media):
        errors.append("source download SHA-256 does not match media")
    video_streams = data.get("video_streams", [])
    audio_streams = data.get("audio_streams", [])
    if not video_streams or not audio_streams:
        errors.append("source download manifest lacks both video and audio stream metadata")
    passes.append("best-quality direct download manifest and media hash checked")


def check_zip(path: Path, errors: list[str], passes: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing ZIP: {path}")
        return
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
        if bad:
            errors.append(f"ZIP corrupt member: {bad}")
        else:
            passes.append("ZIP integrity checked")
    except Exception as exc:
        errors.append(f"ZIP validation failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="project/delivery root")
    ap.add_argument("--video", required=True, help="source video, absolute or relative to root")
    ap.add_argument("--status", choices=["draft", "reviewed", "final"], default="final")
    ap.add_argument("--spec", default="audit/spec.json")
    ap.add_argument("--download-manifest", default="source_download.json")
    ap.add_argument("--quotes", default="audit/quotes.json")
    ap.add_argument("--selection-audit", default="audit/selection_audit.json")
    ap.add_argument("--translation-audit", default="audit/translation_audit.json")
    ap.add_argument("--people", default="audit/people.json")
    ap.add_argument("--subs", default="audit/source_subs.srt")
    ap.add_argument("--asr-report", default="audit/review_asr_xcheck.md")
    ap.add_argument("--frame-audit", default="audit/frame_audit.json")
    ap.add_argument("--images", default="images")
    ap.add_argument("--render", default="audit/render.json")
    ap.add_argument("--manifest", default="audit/release_manifest.json")
    ap.add_argument("--red-team", default="audit/red_team.json")
    ap.add_argument("--package", default="xiaohongshu_package.md")
    # No default: a stale ZIP from a previous delivery must never satisfy this gate.
    ap.add_argument("--zip", help="delivery ZIP; required for reviewed/final")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    passes: list[str] = []
    video = rel(root, args.video)
    probe = probe_video(video, errors, warnings)
    duration = float(probe.get("duration", 0)) if probe else 0.0
    spec = load_json(rel(root, args.spec), errors, "spec")
    selection = load_json(rel(root, args.selection_audit), errors, "selection audit")
    quotes = load_json(rel(root, args.quotes), errors, "quotes")
    translation = load_json(rel(root, args.translation_audit), errors, "translation audit")
    people = load_json(rel(root, args.people), errors, "people")
    subs_text = parse_srt_text(rel(root, args.subs))
    if not subs_text:
        errors.append("missing or empty supplied SRT")
    check_download_manifest(root, video, rel(root, args.download_manifest), errors, passes)
    if spec:
        check_spec(spec, selection, quotes, duration, subs_text, errors, warnings, passes)
    check_translation(root, translation, spec, rel(root, args.asr_report), args.status, errors, warnings, passes)
    check_people(people, spec, errors, passes)
    check_images(root, rel(root, args.images), rel(root, args.render), errors, passes)
    check_frame_audit(rel(root, args.frame_audit), spec, errors, passes)
    check_release_manifest(root, rel(root, args.manifest), spec, args.status, errors, passes)
    check_red_team(root, spec, rel(root, args.red_team), args.status, errors, passes)
    check_package(rel(root, args.package), errors, passes)
    if args.status != "draft":
        if args.zip:
            check_zip(rel(root, args.zip), errors, passes)
        else:
            errors.append("--zip is required for reviewed/final delivery")
    status = "BLOCKED" if errors else ("REVIEWED" if args.status == "reviewed" else "FINAL_ALLOWED")
    report = {"status": status, "requested_status": args.status, "root": str(root), "passes": passes, "warnings": warnings, "errors": errors, "summary": {"pass_count": len(passes), "warning_count": len(warnings), "error_count": len(errors)}}
    if not args.no_report:
        (root / "preflight_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md = ["# Video Quote Image Preflight", "", f"- Requested status: **{args.status}**", f"- Result: **{status}**", "", "## Hard errors"]
        md += [f"- {x}" for x in errors] or ["- None"]
        md += ["", "## Warnings"] + ([f"- {x}" for x in warnings] or ["- None"])
        md += ["", "## Passed checks"] + [f"- {x}" for x in passes]
        (root / "preflight_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
