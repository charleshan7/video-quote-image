import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from media_tools import ffmpeg_exe


class EvidenceExtractorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
    def test_frame_and_subtitle_evidence_scaffolds(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            video = project / "source/source.mp4"
            video.parent.mkdir(parents=True)
            subprocess.run(
                [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=160x120:d=3",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                 "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)],
                check=True,
            )
            spec_path = project / "audit/spec.json"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(json.dumps({"images": [{
                "id": "img01", "hero_time": 1.0, "hero_subject": "Alice",
                "hero_subject_role": "speaker", "quotes": [{
                    "quote_id": "q1", "time": 1.0, "frame_time": 1.0,
                }],
            }]}), encoding="utf-8")
            frame_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/extract_frame_candidates.py"),
                 "source/source.mp4", "--root", str(project), "--reviewer", "tester"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(frame_result.returncode, 0, frame_result.stderr)
            frame_audit = json.loads((project / "audit/frame_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(len(frame_audit["heroes"][0]["candidates"]), 8)
            self.assertEqual(len(frame_audit["images"][0]["rows"][0]["candidates"]), 5)
            subtitle_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/extract_subtitle_audit.py"),
                 "source/source.mp4", "--root", str(project),
                 "--policy", "verified-absent", "--reviewer", "tester"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(subtitle_result.returncode, 0, subtitle_result.stderr)
            subtitle_audit = json.loads((project / "audit/subtitle_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(len(subtitle_audit["samples"]), 3)
            self.assertTrue(all(row["decision"] == "review-required" for row in subtitle_audit["samples"]))


if __name__ == "__main__":
    unittest.main()
