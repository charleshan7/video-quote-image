#!/usr/bin/env python3
"""Create an exact, deterministic release ZIP plus an external hash attestation."""
from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from build_release_manifest import (
    build_manifest,
    checked_artifact,
    checked_relative_value,
    sha256,
    write_manifest,
)


def add_deterministic(zf: zipfile.ZipFile, source: Path, member: str) -> None:
    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(
        info,
        source.read_bytes(),
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--status", choices=["reviewed", "final"], required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--zip", required=True)
    ap.add_argument("--spec", default="audit/spec.json")
    ap.add_argument("--subs", default="audit/source_subs.srt")
    ap.add_argument("--manifest", default="audit/release_manifest.json")
    ap.add_argument("--attestation", default="audit/release_attestation.json")
    ap.add_argument("--branding", choices=["required", "none"], default="required")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    zip_path = Path(args.zip)
    zip_path = zip_path if zip_path.is_absolute() else root / zip_path
    zip_path = zip_path.resolve()
    if zip_path.exists():
        raise SystemExit(f"release ZIP already exists; use a new version path: {zip_path}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(
        root,
        status=args.status,
        version=args.version,
        release_zip=args.zip,
        spec_rel=args.spec,
        subs_rel=args.subs,
        output_rel=args.manifest,
        branding_mode=args.branding,
    )
    manifest_path = write_manifest(root, args.manifest, manifest)
    with tempfile.NamedTemporaryFile(
        prefix="release-", suffix=".zip", dir=zip_path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w") as zf:
            for member in manifest["package_members"]:
                source = manifest_path if member == args.manifest else checked_artifact(root, member)
                add_deterministic(zf, source, member)
        temporary.replace(zip_path)
    finally:
        temporary.unlink(missing_ok=True)

    attestation = {
        "version": args.version,
        "release_zip": args.zip,
        "release_zip_sha256": sha256(zip_path),
        "manifest_path": args.manifest,
        "manifest_sha256": sha256(manifest_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    attestation_path = root / checked_relative_value(args.attestation, "attestation path")
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"zip": str(zip_path), "attestation": str(attestation_path), **attestation},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
