import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from preflight import asr_family, check_frame_audit, check_package, load_json


class PreflightTests(unittest.TestCase):
    def test_whisper_variants_share_family(self):
        self.assertEqual(asr_family("openai-whisper"), asr_family("faster-whisper"))

    def test_load_json_returns_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text('{"ok": true}', encoding="utf-8")
            errors = []
            self.assertEqual(load_json(path, errors, "data"), {"ok": True})
            self.assertEqual(errors, [])

    def test_frame_choice_must_match_spec_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.json"
            path.write_text(json.dumps({
                "heroes": [{"image_id": "img01", "hero_subject": "A", "hero_subject_role": "speaker", "chosen_hero_time": 9, "candidates": list(range(8))}],
                "images": [{"image_id": "img01", "rows": [{"quote_id": "q1", "chosen_frame_time": 8, "candidates": [1, 2, 3, 4, 5]}]}],
            }), encoding="utf-8")
            spec = {"images": [{"id": "img01", "hero_subject": "A", "hero_time": 7, "quotes": [{"quote_id": "q1", "frame_time": 5}]}]}
            errors, passes = [], []
            check_frame_audit(path, spec, errors, passes)
            self.assertTrue(any("differs from spec" in error for error in errors))
            self.assertTrue(any("not in candidates" in error for error in errors))

    def test_package_requires_actual_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.md"
            path.write_text("人物介绍 首发标题 封面大字 轮播顺序 评论区引导 话题标签 image_id quote_ids 淘汰原因", encoding="utf-8")
            errors, passes = [], []
            check_package(path, {"images": [{"id": "img01", "quotes": [{"quote_id": "q1"}]}]}, errors, passes)
            self.assertIn("package missing image_id value: img01", errors)
            self.assertIn("package missing quote_id value: q1", errors)


if __name__ == "__main__":
    unittest.main()
