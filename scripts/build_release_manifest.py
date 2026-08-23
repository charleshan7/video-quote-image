#!/usr/bin/env python3
"""Build the release manifest used by deterministic packaging and preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASE_ARTIFACTS = [
    "source/source_download.json",
    "audit/quotes.json",
    "audit/selection_audit.json",
    "audit/translation_audit.json",
    "audit/people.json",
    "audit/frame_audit.json",
    "audit/subtitle_audit.json",
    "audit/render.json",
    "xiaohongshu_package.md",
    "images/final_contact_sheet.jpg",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_artifact(root: Path, rel_value: str) -> Path:
    rel = Path(rel_value)
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"artifact path must stay inside project root: {rel_value}")
    path = root / rel
    if not path.exists() or not path.is_file():
        raise SystemExit(f"missing artifact: {rel_value}")
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SystemExit(f"artifact may not be a symlink or escape project root: {rel_value}")
    return path


def checked_relative_value(value: str, label: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"{label} must stay inside project root: {value}")
    return str(path)


def build_manifest(
    root: Path,
    *,
    status: str,
    version: str,
    release_zip: str,
    spec_rel: str = "audit/spec.json",
    subs_rel: str = "audit/source_subs.srt",
    output_rel: str = "audit/release_manifest.json",
    branding_mode: str = "required",
) -> dict:
    root = root.resolve()
    spec_path = checked_artifact(root, spec_rel)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    download = json.loads(
        checked_artifact(root, "source/source_download.json").read_text(encoding="utf-8")
    )
    translation = json.loads(
        checked_artifact(root, "audit/translation_audit.json").read_text(encoding="utf-8")
    )

    rounds = {
        int(row["round"]): row
        for row in translation.get("rounds", [])
        if str(row.get("round", "")).isdigit()
    }
    if set(rounds) != {0, 1, 2, 3}:
        raise SystemExit("translation_audit must declare exactly rounds 0, 1, 2 and 3")

    artifact_paths = [*BASE_ARTIFACTS, spec_rel, subs_rel]
    if download.get("info_json_path"):
        artifact_paths.append(str(Path("source") / str(download["info_json_path"])))
    artifact_paths.extend(str(rounds[number]["artifact"]) for number in range(4))
    frame_audit = json.loads(
        checked_artifact(root, "audit/frame_audit.json").read_text(encoding="utf-8")
    )
    for hero in frame_audit.get("heroes", []):
        artifact_paths.extend(str(row.get("artifact")) for row in hero.get("candidates", []))
    for image in frame_audit.get("images", []):
        for row in image.get("rows", []):
            artifact_paths.extend(str(item.get("artifact")) for item in row.get("candidates", []))
    subtitle_audit = json.loads(
        checked_artifact(root, "audit/subtitle_audit.json").read_text(encoding="utf-8")
    )
    for sample in subtitle_audit.get("samples", []):
        artifact_paths.extend([
            str(sample.get("source_artifact")), str(sample.get("processed_artifact"))
        ])
    risk_flags = (spec.get("meta") or {}).get("risk_flags", [])
    if risk_flags:
        artifact_paths.append("audit/red_team.json")

    images = sorted((root / "images").glob("0*.jpg"))
    expected_images = len(spec.get("images", []))
    if len(images) != expected_images:
        raise SystemExit(f"image count {len(images)} != spec groups {expected_images}")
    artifact_paths.extend(str(path.relative_to(root)) for path in images)

    branded = sorted((root / "branded").glob("0*.jpg"))
    brand_metadata = sorted((root / "audit/brand").glob("0*.json"))
    if branding_mode == "required":
        expected_names = {path.name for path in images}
        if {path.name for path in branded} != expected_names:
            raise SystemExit("branding=required needs exactly one branded image for every base image")
        expected_meta = {f"{path.stem}.json" for path in images}
        if {path.name for path in brand_metadata} != expected_meta:
            raise SystemExit("branding=required needs exactly one brand metadata JSON for every image")
        artifact_paths.extend(str(path.relative_to(root)) for path in branded)
        artifact_paths.extend(str(path.relative_to(root)) for path in brand_metadata)
    elif branded or brand_metadata:
        raise SystemExit("branding=none may not include branded images or brand metadata")

    unique_paths = sorted(set(artifact_paths))
    artifact_hashes = {rel: sha256(checked_artifact(root, rel)) for rel in unique_paths}
    manifest_rel = checked_relative_value(output_rel, "manifest path")
    quote_count = sum(len(image.get("quotes", [])) for image in spec.get("images", []))
    return {
        "version": version,
        "status": status,
        "image_count": len(images),
        "quote_count": quote_count,
        "branding_mode": branding_mode,
        "manifest_path": manifest_rel,
        "artifact_hashes": artifact_hashes,
        "package_members": sorted([*artifact_hashes, manifest_rel]),
        "release_zip": release_zip,
        "risk_flags": risk_flags,
        "image_files": [str(path.relative_to(root)) for path in images],
        "branded_files": [str(path.relative_to(root)) for path in branded],
    }


def write_manifest(root: Path, output_rel: str, manifest: dict) -> Path:
    output = root.resolve() / checked_relative_value(output_rel, "manifest path")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--status", choices=["reviewed", "final"], required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--zip", default="../release.zip")
    ap.add_argument("--spec", default="audit/spec.json")
    ap.add_argument("--subs", default="audit/source_subs.srt")
    ap.add_argument("--output", default="audit/release_manifest.json")
    ap.add_argument("--branding", choices=["required", "none"], default="required")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    manifest = build_manifest(
        root,
        status=args.status,
        version=args.version,
        release_zip=args.zip,
        spec_rel=args.spec,
        subs_rel=args.subs,
        output_rel=args.output,
        branding_mode=args.branding,
    )
    write_manifest(root, args.output, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
