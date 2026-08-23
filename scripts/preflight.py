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
import functools
import hashlib
import json
import re
import stat
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from build_release_manifest import BASE_ARTIFACTS
from jsonschema import Draft202012Validator, FormatChecker
from locate_quotes import load_cues, normalize_text
from media_tools import ffprobe_exe

CN_RE = re.compile(r"[\u3400-\u9fff]")
REQUIRED_PEOPLE = ["person_id", "name", "person_type", "role", "source_url", "source_quote", "verified_at", "confidence"]
HERO_ROLES = {"interviewer", "interviewee", "speaker", "narrator", "subject"}
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
    "numbers": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                "ten", "hundred", "thousand", "million", "billion"],
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
    return "unknown"


def load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    if not path.exists():
        errors.append(f"missing {label}: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - invalid JSON must become a gate error
        errors.append(f"invalid JSON {label}: {exc}")
        return None


def load_optional_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_json(path, errors, label)


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
    except Exception as exc:  # noqa: BLE001 - ffprobe/JSON failures share one gate outcome
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


def parse_subtitle_text(path: Path, errors: list[str]) -> str:
    if not path.exists():
        return ""
    try:
        return " ".join(cue.text for cue in load_cues(path))
    except SystemExit as exc:
        errors.append(f"cannot parse supplied subtitles: {exc}")
        return ""


def validate_schema(root: Path, name: str, data: dict[str, Any] | None, errors: list[str]) -> None:
    if data is None:
        return
    schema_path = Path(__file__).parent.parent / "schemas" / f"{name}.schema.json"
    if not schema_path.exists():
        errors.append(f"missing bundled schema: {schema_path.name}")
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for issue in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(x) for x in issue.path) or "$"
        errors.append(f"{name} schema {location}: {issue.message}")


def check_spec(spec: dict[str, Any], selection: dict[str, Any] | None, duration: float,
               subs_text: str, min_images: int, max_images: int, max_quotes: int,
               cn_min: int, cn_max: int,
               strict: bool, errors: list[str], warnings: list[str], passes: list[str]) -> None:
    images = spec.get("images") if isinstance(spec, dict) else None
    if not isinstance(images, list) or not min_images <= len(images) <= max_images:
        errors.append(f"spec.images must contain {min_images}–{max_images} image groups")
        return
    if selection and len(selection.get("images", [])) != len(images):
        errors.append("spec/selection_audit image count mismatch")
    if selection:
        selection_ids = [str(row.get("id", "")) for row in selection.get("images", [])]
        if len(selection_ids) != len(set(selection_ids)):
            errors.append("selection_audit contains duplicate image IDs")
    actual_counts = []
    all_quote_ids: list[str] = []
    image_ids = [str(image.get("id", "")) for image in images]
    if len(image_ids) != len(set(image_ids)):
        errors.append("spec contains duplicate image.id values")
    for index, image in enumerate(images, 1):
        title = image.get("title", f"image {index}")
        quotes = image.get("quotes", [])
        actual_counts.append(len(quotes))
        required_image = ["id", "title", "hero_time"]
        if strict:
            required_image += ["hero_subject_id", "hero_subject", "hero_subject_role", "hero_subject_source_url", "hero_subject_source_quote", "hero_subject_confidence", "structure", "core_quote_index"]
        for key in required_image:
            if key not in image:
                errors.append(f"{title}: missing spec field {key}")
        if strict and image.get("hero_subject_role") not in HERO_ROLES:
            errors.append(f"{title}: unsupported hero_subject_role {image.get('hero_subject_role')}")
        if duration and float(image.get("hero_time", 0)) > duration:
            errors.append(f"{title}: hero_time exceeds source duration")
        if not quotes or len(quotes) > max_quotes:
            errors.append(f"{title}: quote count must be 1–{max_quotes} and is {len(quotes)}")
        core = image.get("core_quote_index")
        if strict and (not isinstance(core, int) or core < 0 or core >= len(quotes)):
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
                if audit.get("structure") != image.get("structure"):
                    errors.append(f"{title}: selection/spec structure mismatch")
                if audit.get("core_quote_index") != image.get("core_quote_index"):
                    errors.append(f"{title}: selection/spec core_quote_index mismatch")
        times = []
        seen_cn: set[str] = set()
        for qi, q in enumerate(quotes, 1):
            prefix = f"{title} q{qi}"
            required_quote = ["quote_id", "time", "match", "source_en", "en", "cn"]
            if strict:
                required_quote.append("frame_time")
            for key in required_quote:
                if key not in q:
                    errors.append(f"{prefix}: missing quote field {key}")
            try:
                time = float(q.get("time", -1))
                frame_time = float(q.get("frame_time", q.get("time", -1)))
                times.append(time)
            except Exception:  # noqa: BLE001 - malformed user-supplied numeric fields
                errors.append(f"{prefix}: invalid time/frame_time")
                continue
            if not (0 <= time <= duration):
                errors.append(f"{prefix}: time outside source duration")
            if not (0 <= frame_time <= duration):
                errors.append(f"{prefix}: frame_time outside source duration")
            quote_id = str(q.get("quote_id", "")).strip()
            if quote_id in all_quote_ids:
                errors.append(f"{prefix}: duplicate quote_id {quote_id}")
            all_quote_ids.append(quote_id)
            cn_len = len(CN_RE.findall(str(q.get("cn", ""))))
            if not cn_min <= cn_len <= cn_max:
                errors.append(f"{prefix}: Chinese length {cn_len} outside {cn_min}–{cn_max}")
            en_len = len(str(q.get("en", "")))
            if en_len > 65:
                errors.append(f"{prefix}: English length {en_len} exceeds 65")
            if q.get("source_en") != q.get("match"):
                errors.append(f"{prefix}: source_en must equal match")
            if q.get("cn") in seen_cn:
                errors.append(f"{prefix}: duplicated Chinese quote")
            seen_cn.add(q.get("cn"))
            if subs_text and normalize_text(str(q.get("match", ""))) not in subs_text:
                errors.append(f"{prefix}: match not found in supplied SRT")
        if times != sorted(times):
            errors.append(f"{title}: quote times are not sorted")
    if len(actual_counts) >= 2 and len(set(actual_counts)) == 1:
        warnings.append("all image groups use the same quote count; prove structure-specific reasons or revise")
    passes.append(f"spec and selection structure checked: {actual_counts}")


def check_quotes_source(quotes_file: dict[str, Any] | None, spec: dict[str, Any] | None,
                        errors: list[str], passes: list[str]) -> None:
    if not quotes_file or not spec:
        return
    source_image_rows = quotes_file.get("images", [])
    source_image_ids = [str(image.get("id")) for image in source_image_rows]
    spec_image_ids = [str(image.get("id")) for image in spec.get("images", [])]
    if len(source_image_ids) != len(set(source_image_ids)):
        errors.append("quotes.json contains duplicate image.id values")
    if set(source_image_ids) != set(spec_image_ids):
        errors.append("quotes/spec image_id sets differ; quotes may not be silently dropped")
    source_images = {str(image.get("id")): image for image in source_image_rows}
    for image in spec.get("images", []):
        image_id = str(image.get("id"))
        source = source_images.get(image_id)
        if source is None:
            errors.append(f"quotes/spec image_id mismatch: {image_id}")
            continue
        source_quotes = {str(q.get("quote_id")): q for q in source.get("quotes", [])}
        source_quote_ids = [str(q.get("quote_id")) for q in source.get("quotes", [])]
        spec_quote_ids = [str(q.get("quote_id")) for q in image.get("quotes", [])]
        if len(source_quote_ids) != len(set(source_quote_ids)):
            errors.append(f"quotes.json image {image_id} contains duplicate quote_id values")
        if set(source_quote_ids) != set(spec_quote_ids):
            errors.append(f"quotes/spec quote_id sets differ for image {image_id}")
        for quote in image.get("quotes", []):
            quote_id = str(quote.get("quote_id"))
            original = source_quotes.get(quote_id)
            if original is None:
                errors.append(f"quotes/spec quote_id mismatch: {quote_id}")
                continue
            if normalize_text(str(original.get("match", ""))) != normalize_text(str(quote.get("match", ""))):
                errors.append(f"quotes/spec match changed for {quote_id}")
    passes.append("quotes.json IDs and source matches checked against spec")


def check_translation(root: Path, audit: dict[str, Any] | None, spec: dict[str, Any] | None,
                      asr_report: Path, subtitles: Path, video: Path, status: str,
                      errors: list[str], warnings: list[str], passes: list[str]) -> None:
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
    starting_error_count = len(errors)
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
    spec_quotes = {
        str(q.get("quote_id")): q
        for image in (spec or {}).get("images", []) for q in image.get("quotes", [])
    }
    artifacts: dict[int, dict[str, Any]] = {}
    for number in range(4):
        record = rounds.get(number)
        if not record:
            continue
        if record.get("status") != "completed":
            errors.append(f"translation round {number} status must be completed, got {record.get('status')}")
        artifact_value = record.get("artifact", default_artifacts[number])
        artifact = safe_project_path(root, str(artifact_value), errors,
                                     f"translation round {number} artifact")
        if artifact is None:
            continue
        if not artifact.exists():
            errors.append(f"translation round {number} missing artifact: {artifact_value}")
            continue
        try:
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - malformed audit artifact
            errors.append(f"translation round {number} artifact is not valid JSON: {exc}")
            continue
        artifacts[number] = data
        validate_schema(root, "asr_report" if number == 0 else f"translation_round_{number}", data, errors)
        if number > 0:
            if data.get("round") != number or data.get("status") != "completed":
                errors.append(f"translation round {number} artifact status/round mismatch")
            if data.get("artifact") != artifact_value:
                errors.append(f"translation round {number} artifact self-path mismatch")
            if data.get("quote_count") != expected:
                errors.append(f"translation round {number} quote_count does not match spec")
        rows = data.get("rows", data.get("quotes", [])) if isinstance(data, dict) else []
        if not isinstance(rows, list) or len(rows) != expected:
            errors.append(f"translation round {number} rows {len(rows) if isinstance(rows, list) else 0} != quote count {expected}")
            continue
        row_ids = []
        for row_index, row in enumerate(rows, 1):
            quote_id = str(row.get("quote_id", ""))
            row_ids.append(quote_id)
            quote = spec_quotes.get(quote_id, {})
            if row.get("source_en") != quote.get("source_en"):
                errors.append(f"translation round {number} {quote_id}: source_en differs from spec")
            if number > 0 and row.get("current_cn") != quote.get("cn"):
                errors.append(f"translation round {number} {quote_id}: current_cn differs from delivered spec")
            adjudication = row.get("adjudication")
            if adjudication == "stop":
                errors.append(f"translation round {number} {quote_id}: stop adjudication blocks delivery")
            if adjudication == "revise" and row.get("changed") is not True:
                errors.append(f"translation round {number} {quote_id}: revise requires changed=true")
            if number == 1 and "revise" in (row.get("checks") or {}).values() and adjudication == "retain":
                errors.append(f"translation round 1 {quote_id}: unresolved revise check cannot be retained")
            if number == 3:
                required_basis = {"round0_asr", "round1_self_check", "round2_mechanical_diff"}
                if not required_basis.issubset(set(row.get("evidence_basis") or [])):
                    errors.append(f"translation round 3 {quote_id}: evidence_basis is incomplete")
                if row.get("claims", {}).get("source_time") != quote.get("time"):
                    errors.append(f"translation round 3 {quote_id}: claims.source_time differs from spec")
        if set(row_ids) != expected_ids or len(row_ids) != len(set(row_ids)):
            errors.append(f"translation round {number} quote_id set does not match spec")
        passes.append(f"translation round {number} complete: {len(rows)} quote rows")
    asr_data = artifacts.get(0) or load_json(asr_report, errors, "quote-level ASR report")
    if asr_data:
        if asr_data.get("status") != "complete" or asr_data.get("missing_count") != 0:
            errors.append("quote-level ASR report is incomplete")
        expected = sum(len(image.get("quotes", [])) for image in (spec or {}).get("images", []))
        if asr_data.get("segment_count") != expected:
            errors.append("ASR report segment_count does not match quote count")
        if video.exists() and asr_data.get("source_video_sha256") != sha256_file(video):
            errors.append("ASR report source video hash does not match current video")
        if subtitles.exists() and asr_data.get("subtitles_sha256") != sha256_file(subtitles):
            errors.append("ASR report subtitle hash does not match current subtitles")
        segment_ids = [str(row.get("quote_id", "")) for row in asr_data.get("segments", [])]
        if set(segment_ids) != expected_ids or len(segment_ids) != len(set(segment_ids)):
            errors.append("ASR report segment quote_id set does not match spec")
    primary_engine = str(audit.get("primary_source_engine") or "").strip()
    second_engine = str(audit.get("second_source_engine") or "").strip()
    declared = audit.get("independent_architecture")
    if declared is False:
        warnings.append("second ASR is explicitly same architecture/family")
    primary_report = (asr_data or {}).get("primary_engine") or {}
    second_report = (asr_data or {}).get("second_engine") or {}
    if primary_report.get("name") != primary_engine:
        errors.append("translation audit primary engine does not match ASR report")
    if second_report.get("name") != second_engine:
        errors.append("translation audit second engine does not match ASR report")
    if status == "final":
        # Fail closed: silence is not evidence. The engines must be named, and the
        # family comparison is derived from those names so a wrong self-declaration
        # cannot pass the gate on its own.
        if declared is not True:
            errors.append("final status requires translation_audit.independent_architecture=true")
        for field, value in (("primary_source_engine", primary_engine), ("second_source_engine", second_engine)):
            if not value:
                errors.append(f"final status requires translation_audit.{field}")
        primary_family = primary_report.get("family") or asr_family(primary_engine)
        second_family = second_report.get("family") or asr_family(second_engine)
        derived_primary = asr_family(primary_engine)
        derived_second = asr_family(second_engine)
        if "unknown" in (primary_family, second_family, derived_primary, derived_second):
            errors.append("final status requires two recognized ASR architecture families")
        if derived_primary != "unknown" and derived_primary != primary_family:
            errors.append("primary ASR reported family conflicts with its recognized engine name")
        if derived_second != "unknown" and derived_second != second_family:
            errors.append("second ASR reported family conflicts with its recognized engine name")
        if primary_engine and second_engine and primary_family == second_family:
            errors.append(
                f"primary and second ASR share the {primary_family} family: "
                f"{primary_engine} / {second_engine}"
            )
    if len(errors) == starting_error_count:
        passes.append("four-round calibration gate satisfied")


def check_people(people: dict[str, Any] | None, spec: dict[str, Any] | None, errors: list[str], passes: list[str]) -> None:
    if not people or not isinstance(people.get("people"), list) or len(people["people"]) < 1:
        errors.append("people.json must contain at least one verified person")
        return
    for person in people["people"]:
        for key in REQUIRED_PEOPLE:
            if not person.get(key):
                errors.append(f"people record {person.get('name')}: missing {key}")
    person_ids = [str(p.get("person_id")) for p in people["people"]]
    if len(person_ids) != len(set(person_ids)):
        errors.append("people.json contains duplicate person_id values")
    records = {str(p.get("person_id")): p for p in people["people"]}
    for image in (spec or {}).get("images", []):
        person_id = str(image.get("hero_subject_id"))
        record = records.get(person_id)
        if record is None:
            errors.append(f"hero subject missing from people.json: {person_id}")
        elif record.get("person_type") not in HERO_ROLES:
            errors.append(f"hero subject {person_id} has unsupported person_type")
        elif record.get("name") != image.get("hero_subject"):
            errors.append(f"hero subject name differs from people.json: {person_id}")
        else:
            comparisons = {
                "person_type": "hero_subject_role",
                "source_url": "hero_subject_source_url",
                "source_quote": "hero_subject_source_quote",
                "confidence": "hero_subject_confidence",
            }
            for people_field, spec_field in comparisons.items():
                if record.get(people_field) != image.get(spec_field):
                    errors.append(f"hero subject {person_id}: {people_field} differs from spec")
    if any(p.get("person_type") in HERO_ROLES for p in people["people"]):
        passes.append("people records contain an eligible hero subject")


def check_images(root: Path, image_dir: Path, render: Path, spec_path: Path, video: Path,
                 spec: dict[str, Any] | None, min_images: int, max_images: int,
                 strict: bool, errors: list[str], warnings: list[str], passes: list[str]) -> None:
    if not image_dir.exists():
        errors.append(f"missing image directory: {image_dir}")
        return
    from PIL import Image
    images = sorted(image_dir.glob("0*.jpg"))
    if len(images) < min_images or len(images) > max_images:
        errors.append(f"image count must be {min_images}–{max_images}, found {len(images)}")
    if spec and len(images) != len(spec.get("images", [])):
        errors.append("image file count does not match spec image count")
    for path in images:
        try:
            with Image.open(path) as opened:
                if opened.size != (1440, 1920):
                    errors.append(f"{path.name}: expected 1440x1920")
        except Exception as exc:  # noqa: BLE001 - Pillow errors must become gate errors
            errors.append(f"cannot read {path}: {exc}")
    render_data = load_json(render, errors, "render metadata")
    if render_data:
        if render_data.get("width") != 1440 or render_data.get("height") != 1920:
            errors.append("render.json dimensions must be 1440x1920")
        for warning in render_data.get("warnings", []):
            (errors if strict else warnings).append(f"renderer warning: {warning}")
        if spec_path.exists() and render_data.get("spec_sha256") != sha256_file(spec_path):
            errors.append("render.json spec hash does not match current spec")
        if video.exists() and render_data.get("source_video_sha256") != sha256_file(video):
            errors.append("render.json source video hash does not match current video")
        for font_name, font_value in (render_data.get("fonts") or {}).items():
            font_path = Path(str(font_value))
            if not font_path.exists():
                errors.append(f"render font is no longer available: {font_name}")
            elif (render_data.get("font_sha256") or {}).get(font_name) != sha256_file(font_path):
                errors.append(f"render font hash mismatch: {font_name}")
        renderer_path = Path(__file__).parent / "render_quote_cards.py"
        if render_data.get("renderer_sha256") != sha256_file(renderer_path):
            warnings.append("renderer code differs from the version recorded in render.json")
        records = render_data.get("outputs", [])
        expected_ids = [str(image.get("id")) for image in (spec or {}).get("images", [])]
        if [str(row.get("image_id")) for row in records] != expected_ids:
            errors.append("render.json output image_id order does not match spec")
        for row in records:
            output = image_dir / str(row.get("filename", ""))
            if not output.exists() or row.get("sha256") != sha256_file(output):
                errors.append(f"render output hash mismatch: {row.get('filename')}")
    passes.append(f"image dimensions/count/render warnings checked: {len(images)}")


def check_subtitle_audit(root: Path, audit_path: Path, render_path: Path, video: Path,
                         errors: list[str], passes: list[str]) -> None:
    data = load_json(audit_path, errors, "burned-subtitle audit")
    render = load_json(render_path, errors, "render metadata for subtitle audit")
    if not data or not render:
        return
    validate_schema(root, "subtitle_audit", data, errors)
    if video.exists() and data.get("source_video_sha256") != sha256_file(video):
        errors.append("subtitle audit source video hash does not match current video")
    if data.get("policy") != render.get("source_subtitle_policy"):
        errors.append("subtitle audit policy does not match render.json")
    if not time_matches(data.get("crop_bottom", 0), render.get("source_crop_bottom", 0)):
        errors.append("subtitle audit crop_bottom does not match render.json")
    expected_decision = "cropped-out" if data.get("policy") == "cropped" else "absent"
    for index, sample in enumerate(data.get("samples", []), 1):
        if sample.get("decision") != expected_decision:
            errors.append(f"subtitle audit sample {index}: decision must be {expected_decision}")
        for prefix in ("source", "processed"):
            artifact = safe_project_path(
                root, str(sample.get(f"{prefix}_artifact", "")), errors,
                f"subtitle sample {index} {prefix}",
            )
            if artifact is None:
                continue
            if not artifact.exists():
                errors.append(f"subtitle audit sample {index}: missing {prefix} artifact")
            elif sample.get(f"{prefix}_sha256") != sha256_file(artifact):
                errors.append(f"subtitle audit sample {index}: {prefix} hash mismatch")
    passes.append(f"burned-subtitle evidence checked: {len(data.get('samples', []))} samples")


def time_matches(left: Any, right: Any, tolerance: float = 0.002) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def frame_candidate_times(root: Path, candidates: list[Any], label: str,
                          errors: list[str]) -> list[float]:
    times: list[float] = []
    for index, item in enumerate(candidates, 1):
        if not isinstance(item, dict):
            errors.append(f"{label} candidate {index}: must be an evidence object")
            continue
        try:
            times.append(float(item.get("time")))
        except (TypeError, ValueError):
            errors.append(f"{label} candidate {index}: invalid time")
        artifact = safe_project_path(root, str(item.get("artifact", "")), errors,
                                     f"{label} candidate artifact")
        if artifact is None:
            continue
        if not artifact.exists():
            errors.append(f"{label} candidate {index}: missing artifact")
        elif item.get("sha256") != sha256_file(artifact):
            errors.append(f"{label} candidate {index}: artifact hash mismatch")
    if len(times) != len(set(times)):
        errors.append(f"{label}: candidate times must be distinct")
    return times


def check_frame_audit(root: Path, frame_audit: Path, video: Path,
                      spec: dict[str, Any] | None, errors: list[str], passes: list[str]) -> None:
    data = load_json(frame_audit, errors, "frame audit")
    if not data or not spec:
        return
    if video.exists() and data.get("source_video_sha256") != sha256_file(video):
        errors.append("frame audit source video hash does not match current video")
    hero_rows = data.get("heroes", [])
    expected_hero_ids = {str(image.get("id")) for image in spec.get("images", [])}
    actual_hero_ids = {str(row.get("image_id")) for row in hero_rows}
    spec_images = {str(image.get("id")): image for image in spec.get("images", [])}
    if actual_hero_ids != expected_hero_ids:
        errors.append("hero frame audit image_id set does not match spec")
    for row in hero_rows:
        if row.get("hero_subject_role") not in HERO_ROLES:
            errors.append(f"hero {row.get('image_id')}: unsupported role")
        if not row.get("hero_subject") or row.get("chosen_hero_time") is None:
            errors.append(f"hero {row.get('image_id')}: missing subject or chosen_hero_time")
        candidates = row.get("candidates", [])
        if len(candidates) < 8:
            errors.append(f"hero {row.get('image_id')}: fewer than 8 wide-window candidates")
        image = spec_images.get(str(row.get("image_id")), {})
        if not time_matches(row.get("chosen_hero_time"), image.get("hero_time")):
            errors.append(f"hero {row.get('image_id')}: chosen_hero_time differs from spec")
        times = frame_candidate_times(root, candidates, f"hero {row.get('image_id')}", errors)
        if not any(time_matches(row.get("chosen_hero_time"), time) for time in times):
            errors.append(f"hero {row.get('image_id')}: chosen time is not in candidates")
        if row.get("hero_subject") != image.get("hero_subject"):
            errors.append(f"hero {row.get('image_id')}: subject differs from spec")
    expected = sum(len(i.get("quotes", [])) for i in spec.get("images", []))
    expected_ids = {str(q.get("quote_id")) for image in spec.get("images", []) for q in image.get("quotes", [])}
    image_audit_rows = data.get("images", [])
    actual_image_ids = [str(image.get("image_id")) for image in image_audit_rows]
    if set(actual_image_ids) != expected_hero_ids or len(actual_image_ids) != len(set(actual_image_ids)):
        errors.append("quote frame audit image_id set does not match spec")
    rows = [row for image in image_audit_rows for row in image.get("rows", [])]
    if len(rows) != expected:
        errors.append(f"frame audit rows {len(rows)} != quote count {expected}")
    frame_ids = []
    spec_quotes = {str(q.get("quote_id")): q for image in spec.get("images", []) for q in image.get("quotes", [])}
    for row in rows:
        if not row.get("quote_id"):
            errors.append(f"frame audit q{row.get('quote_index')}: missing quote_id")
        frame_ids.append(str(row.get("quote_id", "")))
        candidates = row.get("candidates", [])
        if len(candidates) < 5:
            errors.append(f"frame audit q{row.get('quote_index')}: fewer than 5 candidates")
        if "chosen_frame_time" not in row:
            errors.append(f"frame audit q{row.get('quote_index')}: missing chosen_frame_time")
        quote = spec_quotes.get(str(row.get("quote_id")), {})
        if not time_matches(row.get("chosen_frame_time"), quote.get("frame_time")):
            errors.append(f"frame audit {row.get('quote_id')}: chosen_frame_time differs from spec")
        times = frame_candidate_times(root, candidates, f"frame {row.get('quote_id')}", errors)
        if not any(time_matches(row.get("chosen_frame_time"), time) for time in times):
            errors.append(f"frame audit {row.get('quote_id')}: chosen time is not in candidates")
    if set(frame_ids) != expected_ids or len(frame_ids) != len(set(frame_ids)):
        errors.append("frame audit quote_id set does not match spec")
    passes.append(f"frame audit checked: {len(rows)} quotes")


def check_package(package: Path, spec: dict[str, Any] | None, errors: list[str], passes: list[str]) -> None:
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
    for image in (spec or {}).get("images", []):
        image_id = str(image.get("id", ""))
        if image_id and image_id not in text:
            errors.append(f"package missing image_id value: {image_id}")
        for quote in image.get("quotes", []):
            quote_id = str(quote.get("quote_id", ""))
            if quote_id and quote_id not in text:
                errors.append(f"package missing quote_id value: {quote_id}")
    passes.append("publication package sections and traceability checked")


@functools.cache
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_project_path(root: Path, value: str, errors: list[str], label: str) -> Path | None:
    root = root.resolve()
    rel_path = Path(value)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        errors.append(f"{label} must stay inside project root: {value}")
        return None
    path = root / rel_path
    if path.is_symlink():
        errors.append(f"{label} may not be a symlink: {value}")
        return None
    try:
        if not path.resolve().is_relative_to(root):
            errors.append(f"{label} escapes project root: {value}")
            return None
    except OSError as exc:
        errors.append(f"cannot resolve {label} {value}: {exc}")
        return None
    return path


def check_release_manifest(root: Path, manifest: Path, spec: dict[str, Any] | None,
                           status: str, errors: list[str], passes: list[str],
                           required_paths: set[str] | None = None) -> None:
    data = load_json(manifest, errors, "release manifest")
    if not data or status == "draft":
        return
    required = ["version", "status", "image_count", "quote_count", "branding_mode",
                "manifest_path", "artifact_hashes", "package_members", "release_zip"]
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
    artifact_hashes = data.get("artifact_hashes", {})
    expected_paths = required_paths or (set(BASE_ARTIFACTS) | {"audit/spec.json", "audit/source_subs.srt"})
    translation_path = root / "audit/translation_audit.json"
    if translation_path.exists():
        try:
            translation = json.loads(translation_path.read_text(encoding="utf-8"))
            expected_paths.update(str(row.get("artifact")) for row in translation.get("rounds", []))
        except Exception as exc:  # noqa: BLE001 - convert drift into a manifest gate error
            errors.append(f"cannot derive translation artifacts for release manifest: {exc}")
    download_path = root / "source/source_download.json"
    if download_path.exists():
        try:
            download_data = json.loads(download_path.read_text(encoding="utf-8"))
            if download_data.get("info_json_path"):
                expected_paths.add(str(Path("source") / str(download_data["info_json_path"])))
        except Exception as exc:  # noqa: BLE001 - convert drift into a manifest gate error
            errors.append(f"cannot derive download evidence for release manifest: {exc}")
    frame_audit_path = root / "audit/frame_audit.json"
    if frame_audit_path.exists():
        try:
            frame_data = json.loads(frame_audit_path.read_text(encoding="utf-8"))
            for hero in frame_data.get("heroes", []):
                expected_paths.update(str(row.get("artifact")) for row in hero.get("candidates", []))
            for image in frame_data.get("images", []):
                for row in image.get("rows", []):
                    expected_paths.update(str(item.get("artifact")) for item in row.get("candidates", []))
        except Exception as exc:  # noqa: BLE001 - convert drift into a manifest gate error
            errors.append(f"cannot derive frame evidence for release manifest: {exc}")
    subtitle_audit_path = root / "audit/subtitle_audit.json"
    if subtitle_audit_path.exists():
        try:
            subtitle_data = json.loads(subtitle_audit_path.read_text(encoding="utf-8"))
            for sample in subtitle_data.get("samples", []):
                expected_paths.update([
                    str(sample.get("source_artifact")), str(sample.get("processed_artifact"))
                ])
        except Exception as exc:  # noqa: BLE001 - convert drift into a manifest gate error
            errors.append(f"cannot derive subtitle evidence for release manifest: {exc}")
    if (spec or {}).get("meta", {}).get("risk_flags"):
        expected_paths.add("audit/red_team.json")
    base_images = sorted((root / "images").glob("0*.jpg"))
    expected_paths.update(str(path.relative_to(root)) for path in base_images)
    branded = sorted((root / "branded").glob("0*.jpg"))
    brand_meta = sorted((root / "audit/brand").glob("0*.json"))
    if data.get("branding_mode") == "required":
        if {path.name for path in branded} != {path.name for path in base_images}:
            errors.append("branding=required needs one branded image per base image")
        if {path.name for path in brand_meta} != {f"{path.stem}.json" for path in base_images}:
            errors.append("branding=required needs one brand metadata JSON per base image")
        expected_paths.update(str(path.relative_to(root)) for path in branded)
        expected_paths.update(str(path.relative_to(root)) for path in brand_meta)
        for meta_path in brand_meta:
            meta = load_json(meta_path, errors, f"brand metadata {meta_path.name}")
            validate_schema(root, "brand_metadata", meta, errors)
            if not meta:
                continue
            expected_source = root / "images" / f"{meta_path.stem}.jpg"
            expected_output = root / "branded" / f"{meta_path.stem}.jpg"
            source = rel(root, str(meta.get("source", "")))
            output = rel(root, str(meta.get("output", "")))
            if source.resolve() != expected_source.resolve() or output.resolve() != expected_output.resolve():
                errors.append(f"brand metadata {meta_path.name}: source/output path mismatch")
            if source.exists() and meta.get("source_sha256") != sha256_file(source):
                errors.append(f"brand metadata {meta_path.name}: source hash mismatch")
            if output.exists() and meta.get("output_sha256") != sha256_file(output):
                errors.append(f"brand metadata {meta_path.name}: output hash mismatch")
            render_meta = rel(root, str(meta.get("render_metadata", "")))
            if render_meta.exists() and meta.get("render_sha256") != sha256_file(render_meta):
                errors.append(f"brand metadata {meta_path.name}: render hash mismatch")
            font_path = Path(str(meta.get("latin_font", "")))
            if font_path.exists() and meta.get("latin_font_sha256") != sha256_file(font_path):
                errors.append(f"brand metadata {meta_path.name}: font hash mismatch")
    elif branded or brand_meta:
        errors.append("branding=none may not contain branded files")
    missing_hashes = expected_paths - set(artifact_hashes)
    extra_hashes = set(artifact_hashes) - expected_paths
    if missing_hashes:
        errors.append(f"release manifest missing mandatory artifact hashes: {sorted(missing_hashes)}")
    if extra_hashes:
        errors.append(f"release manifest contains unexpected artifact hashes: {sorted(extra_hashes)}")
    expected_members = set(artifact_hashes) | {str(data.get("manifest_path", ""))}
    if set(data.get("package_members", [])) != expected_members:
        errors.append("release manifest package_members must exactly equal artifacts plus manifest")
    try:
        actual_manifest_rel = str(manifest.relative_to(root))
    except ValueError:
        actual_manifest_rel = ""
    if data.get("manifest_path") != actual_manifest_rel:
        errors.append("release manifest manifest_path does not match current file")
    for rel_path, expected_hash in artifact_hashes.items():
        artifact = safe_project_path(root, rel_path, errors, "release artifact")
        if artifact is None:
            continue
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
    validate_schema(root, "red_team", data, errors)
    expected = sum(len(i.get("quotes", [])) for i in spec.get("images", []))
    expected_ids = {str(q.get("quote_id")) for image in spec.get("images", []) for q in image.get("quotes", [])}
    rows = data.get("rows", [])
    if data.get("status") != "completed":
        errors.append("red-team audit status must be completed")
    if len(rows) != expected:
        errors.append(f"red-team rows {len(rows)} != quote count {expected}")
    red_ids = []
    for index, row in enumerate(rows, 1):
        quote_id = str(row.get("quote_id", ""))
        red_ids.append(quote_id)
        for field in ["quote_id", "risk_tags", "challenge", "decision"]:
            if field not in row:
                errors.append(f"red-team row {index} missing {field}")
        if row.get("decision") not in ("retain", "revise", "stop"):
            errors.append(f"red-team row {index} decision must be retain/revise/stop")
        if row.get("decision") == "stop":
            errors.append(f"red-team {quote_id}: stop decision blocks delivery")
        if row.get("decision") == "revise":
            revision = str(row.get("revision", "")).strip()
            if not revision:
                errors.append(f"red-team {quote_id}: revise requires a non-empty revision")
            spec_quote = next(
                (q for image in spec.get("images", []) for q in image.get("quotes", [])
                 if str(q.get("quote_id")) == quote_id),
                {},
            )
            if revision and revision != spec_quote.get("cn"):
                errors.append(f"red-team {quote_id}: revision differs from delivered spec.cn")
        if not row.get("reviewer") or not row.get("reviewed_at"):
            errors.append(f"red-team {quote_id}: reviewer and reviewed_at are required")
    if set(red_ids) != expected_ids or len(red_ids) != len(set(red_ids)):
        errors.append("red-team quote_id set does not match spec")
    passes.append(f"red-team audit checked for triggers: {sorted(active)}")


def check_download_manifest(root: Path, video: Path, manifest: Path, errors: list[str], passes: list[str]) -> None:
    data = load_json(manifest, errors, "source download manifest")
    if not data:
        return
    if data.get("download_mode") != "direct":
        errors.append("source download must be direct, not a preview or screenshot")
    if data.get("quality_scope") != "best_visible_to_yt_dlp" or data.get("best_visible_to_yt_dlp") is not True:
        errors.append("source download lacks evidence for best format visible to yt-dlp")
    if data.get("format_selector") != "bestvideo*+bestaudio/best":
        errors.append("source download manifest must record bestvideo*+bestaudio/best selector")
    media_value = Path(str(data.get("media_path", "")))
    media = media_value if media_value.is_absolute() else manifest.parent / media_value
    if not media.exists():
        errors.append(f"source download media missing: {media}")
    if media.resolve() != video.resolve():
        errors.append("source download manifest media_path does not match preflight video")
    if media.exists() and data.get("file_sha256") != sha256_file(media):
        errors.append("source download SHA-256 does not match media")
    info_value = data.get("info_json_path")
    if info_value:
        info_path = manifest.parent / str(info_value)
        if not info_path.exists():
            errors.append("source download info JSON is missing")
        elif data.get("info_json_sha256") != sha256_file(info_path):
            errors.append("source download info JSON hash mismatch")
    else:
        errors.append("source download manifest lacks the yt-dlp info JSON path")
    video_streams = data.get("video_streams", [])
    audio_streams = data.get("audio_streams", [])
    if not video_streams or not audio_streams:
        errors.append("source download manifest lacks both video and audio stream metadata")
    for key in ["yt_dlp_version", "extractor", "source_id", "downloaded_at",
                "quality_evidence", "configuration_scope"]:
        if not data.get(key):
            errors.append(f"source download manifest missing {key}")
    if not data.get("yt_dlp_format_id") and not data.get("yt_dlp_requested_formats"):
        errors.append("source download manifest lacks selected yt-dlp format IDs")
    passes.append("best-quality direct download manifest and media hash checked")


def check_zip(path: Path, root: Path, manifest: dict[str, Any] | None,
              errors: list[str], passes: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing ZIP: {path}")
        return
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            infos = zf.infolist()
            raw_names = [info.filename for info in infos]
            names = set(raw_names)
            duplicates = sorted(name for name, count in Counter(raw_names).items() if count > 1)
            if duplicates:
                errors.append(f"ZIP contains duplicate member names: {duplicates[:3]}")
            unsafe = [name for name in raw_names if name.startswith("/") or ".." in Path(name).parts]
            if unsafe:
                errors.append(f"ZIP contains unsafe paths: {unsafe[:3]}")
            symlinks = [info.filename for info in infos if stat.S_ISLNK(info.external_attr >> 16)]
            if symlinks:
                errors.append(f"ZIP contains symbolic links: {symlinks[:3]}")
            encrypted = [info.filename for info in infos if info.flag_bits & 0x1]
            if encrypted:
                errors.append(f"ZIP contains encrypted members: {encrypted[:3]}")
            expected_members = set((manifest or {}).get("package_members", []))
            if names != expected_members:
                errors.append(
                    "ZIP member set differs from manifest: "
                    f"missing={sorted(expected_members - names)}, extra={sorted(names - expected_members)}"
                )
            for rel_path, expected_hash in (manifest or {}).get("artifact_hashes", {}).items():
                normalized = str(Path(rel_path)).replace("\\", "/")
                candidates = [name for name in raw_names if name == normalized]
                if len(candidates) != 1:
                    errors.append(f"ZIP must contain exactly one copy of {rel_path}")
                    continue
                if hashlib.sha256(zf.read(candidates[0])).hexdigest() != expected_hash:
                    errors.append(f"ZIP member hash mismatch: {rel_path}")
            manifest_member = str((manifest or {}).get("manifest_path", ""))
            external_manifest = safe_project_path(root, manifest_member, errors, "manifest member")
            if (manifest_member in names and external_manifest and external_manifest.exists()
                    and zf.read(manifest_member) != external_manifest.read_bytes()):
                errors.append("ZIP manifest bytes differ from external release manifest")
        if bad:
            errors.append(f"ZIP corrupt member: {bad}")
        else:
            passes.append("ZIP integrity, paths and manifest member hashes checked")
    except Exception as exc:  # noqa: BLE001 - any ZIP parsing failure blocks delivery
        errors.append(f"ZIP validation failed: {exc}")


def check_attestation(root: Path, attestation_path: Path, zip_path: Path,
                      manifest_path: Path, errors: list[str], passes: list[str]) -> None:
    data = load_json(attestation_path, errors, "release attestation")
    if not data:
        return
    if not zip_path.exists() or not manifest_path.exists():
        errors.append("release attestation inputs are missing")
        return
    if data.get("release_zip_sha256") != sha256_file(zip_path):
        errors.append("release attestation ZIP hash mismatch")
    if data.get("manifest_sha256") != sha256_file(manifest_path):
        errors.append("release attestation manifest hash mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - invalid manifest is a gate error
        errors.append(f"cannot read manifest for release attestation: {exc}")
        manifest = {}
    if data.get("release_zip") != manifest.get("release_zip"):
        errors.append("release attestation release_zip differs from manifest")
    if data.get("version") != manifest.get("version"):
        errors.append("release attestation version differs from manifest")
    try:
        manifest_rel = str(manifest_path.relative_to(root))
    except ValueError:
        manifest_rel = ""
    if data.get("manifest_path") != manifest_rel:
        errors.append("release attestation manifest_path mismatch")
    passes.append("release ZIP and manifest attestation hashes checked")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="project/delivery root")
    ap.add_argument("--video", required=True, help="source video, absolute or relative to root")
    ap.add_argument("--status", choices=["draft", "reviewed", "final"], default="final")
    ap.add_argument("--spec", default="audit/spec.json")
    ap.add_argument("--download-manifest", default="source/source_download.json")
    ap.add_argument("--quotes", default="audit/quotes.json")
    ap.add_argument("--selection-audit", default="audit/selection_audit.json")
    ap.add_argument("--translation-audit", default="audit/translation_audit.json")
    ap.add_argument("--people", default="audit/people.json")
    ap.add_argument("--subs", default="audit/source_subs.srt")
    ap.add_argument("--asr-report", default="audit/review_asr_xcheck.json")
    ap.add_argument("--frame-audit", default="audit/frame_audit.json")
    ap.add_argument("--subtitle-audit", default="audit/subtitle_audit.json")
    ap.add_argument("--images", default="images")
    ap.add_argument("--render", default="audit/render.json")
    ap.add_argument("--manifest", default="audit/release_manifest.json")
    ap.add_argument("--attestation", default="audit/release_attestation.json")
    ap.add_argument("--red-team", default="audit/red_team.json")
    ap.add_argument("--package", default="xiaohongshu_package.md")
    # No default: a stale ZIP from a previous delivery must never satisfy this gate.
    ap.add_argument("--zip", help="delivery ZIP; required for reviewed/final")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--min-images", type=int, default=4)
    ap.add_argument("--max-images", type=int, default=6)
    ap.add_argument("--max-quotes", type=int, default=8)
    ap.add_argument("--cn-min", type=int, default=10)
    ap.add_argument("--cn-max", type=int, default=16)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    passes: list[str] = []
    video = rel(root, args.video)
    probe = probe_video(video, errors, warnings)
    duration = float(probe.get("duration", 0)) if probe else 0.0
    spec = load_json(rel(root, args.spec), errors, "spec")
    strict = args.status != "draft"
    selection = (load_json if strict else load_optional_json)(rel(root, args.selection_audit), errors, "selection audit")
    quotes = load_json(rel(root, args.quotes), errors, "quotes")
    translation = (load_json if strict else load_optional_json)(rel(root, args.translation_audit), errors, "translation audit")
    people = (load_json if strict else load_optional_json)(rel(root, args.people), errors, "people")
    subs_text = parse_subtitle_text(rel(root, args.subs), errors)
    if not subs_text:
        errors.append("missing or empty supplied SRT")
    check_download_manifest(root, video, rel(root, args.download_manifest), errors, passes)
    validate_schema(root, "source_download",
                    load_optional_json(rel(root, args.download_manifest), errors, "source download manifest schema input"), errors)
    for name, data in (("spec", spec), ("quotes", quotes), ("selection_audit", selection),
                       ("translation_audit", translation), ("people", people)):
        validate_schema(root, name, data, errors)
    if spec:
        check_spec(spec, selection, duration, subs_text, args.min_images, args.max_images,
                   args.max_quotes, args.cn_min, args.cn_max, strict, errors, warnings, passes)
    check_quotes_source(quotes, spec, errors, passes)
    check_images(root, rel(root, args.images), rel(root, args.render), rel(root, args.spec),
                 video, spec, args.min_images, args.max_images, strict, errors, warnings, passes)
    if strict:
        validate_schema(root, "render",
                        load_optional_json(rel(root, args.render), errors, "render schema input"), errors)
        check_subtitle_audit(root, rel(root, args.subtitle_audit), rel(root, args.render),
                             video, errors, passes)
    manifest_data = None
    if strict:
        check_translation(root, translation, spec, rel(root, args.asr_report),
                          rel(root, args.subs), video, args.status,
                          errors, warnings, passes)
        check_people(people, spec, errors, passes)
        validate_schema(root, "frame_audit",
                        load_optional_json(rel(root, args.frame_audit), errors, "frame audit schema input"), errors)
        check_frame_audit(root, rel(root, args.frame_audit), video, spec, errors, passes)
        manifest_data = load_json(rel(root, args.manifest), errors, "release manifest")
        validate_schema(root, "release_manifest", manifest_data, errors)
        if manifest_data:
            required_release_paths = {
                args.download_manifest, args.spec, args.quotes, args.selection_audit,
                args.translation_audit, args.people, args.subs, args.asr_report,
                args.frame_audit, args.subtitle_audit, args.render, args.package,
                "images/final_contact_sheet.jpg",
            }
            check_release_manifest(root, rel(root, args.manifest), spec, args.status,
                                   errors, passes, required_release_paths)
        check_red_team(root, spec, rel(root, args.red_team), args.status, errors, passes)
        check_package(rel(root, args.package), spec, errors, passes)
    if args.status != "draft":
        if args.zip:
            if manifest_data and Path(str(manifest_data.get("release_zip", ""))) != Path(args.zip):
                errors.append("CLI --zip does not match release_manifest.release_zip")
            zip_path = rel(root, args.zip)
            check_zip(zip_path, root, manifest_data, errors, passes)
            check_attestation(root, rel(root, args.attestation), zip_path,
                              rel(root, args.manifest), errors, passes)
        else:
            errors.append("--zip is required for reviewed/final delivery")
    allowed = {"draft": "DRAFT_ALLOWED", "reviewed": "REVIEWED_ALLOWED", "final": "FINAL_ALLOWED"}
    status = "BLOCKED" if errors else allowed[args.status]
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
