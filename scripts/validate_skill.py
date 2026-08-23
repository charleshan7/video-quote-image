#!/usr/bin/env python3
"""Repository-local structural validation for SKILL.md and its relative links."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
EXPECTED_SKILL_NAME = "video-quote-image"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", nargs="?", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    skill = root / "SKILL.md"
    errors = []
    if not skill.exists():
        errors.append("missing SKILL.md")
    else:
        text = skill.read_text(encoding="utf-8")
        match = FRONTMATTER.match(text)
        if not match:
            errors.append("SKILL.md must start with YAML frontmatter")
        else:
            metadata = yaml.safe_load(match.group(1)) or {}
            if metadata.get("name") != EXPECTED_SKILL_NAME:
                errors.append(
                    f"frontmatter name must equal {EXPECTED_SKILL_NAME!r}"
                )
            if not str(metadata.get("description", "")).strip():
                errors.append("frontmatter description is required")
        for target in LINK.findall(text):
            if "://" in target or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (root / relative).exists():
                errors.append(f"broken relative link: {target}")
        if re.search(r"\b(TODO|TBD)\b", text, re.IGNORECASE):
            errors.append("SKILL.md contains unfinished TODO/TBD text")
    for error in errors:
        print(f"ERROR {error}")
    if not errors:
        print("Skill structure is valid")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
