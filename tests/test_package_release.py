import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageReleaseTests(unittest.TestCase):
    def test_package_member_set_is_exact_and_attested(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            spec = {"meta": {"risk_flags": []},
                    "images": [{"id": "img01", "quotes": [{"quote_id": "q1"}]}]}
            files = {
                "source/source_download.json": {},
                "audit/spec.json": spec,
                "audit/quotes.json": {},
                "audit/selection_audit.json": {},
                "audit/people.json": {},
                "audit/frame_audit.json": {"heroes": [], "images": []},
                "audit/subtitle_audit.json": {"samples": []},
                "audit/render.json": {},
                "audit/source_subs.srt": "subtitle",
                "xiaohongshu_package.md": "package",
                "images/01_test.jpg": b"image",
                "images/final_contact_sheet.jpg": b"sheet",
            }
            rounds = []
            for number in range(4):
                rel = f"audit/round{number}.json"
                files[rel] = {"rows": []}
                rounds.append({"round": number, "status": "completed", "artifact": rel})
            files["audit/translation_audit.json"] = {"rounds": rounds}
            for rel, value in files.items():
                path = project / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value, bytes):
                    path.write_bytes(value)
                elif isinstance(value, str):
                    path.write_text(value, encoding="utf-8")
                else:
                    path.write_text(json.dumps(value), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/package_release.py"),
                 "--root", str(project), "--status", "final", "--version", "v1",
                 "--zip", "../release.zip", "--branding", "none"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((project / "audit/release_manifest.json").read_text(encoding="utf-8"))
            release = project.parent / "release.zip"
            with zipfile.ZipFile(release) as zf:
                self.assertEqual(set(zf.namelist()), set(manifest["package_members"]))
                self.assertEqual(
                    zf.read("audit/release_manifest.json"),
                    (project / "audit/release_manifest.json").read_bytes(),
                )
            attestation = json.loads((project / "audit/release_attestation.json").read_text(encoding="utf-8"))
            self.assertEqual(
                attestation["release_zip_sha256"], hashlib.sha256(release.read_bytes()).hexdigest()
            )


if __name__ == "__main__":
    unittest.main()
