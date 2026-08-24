import hashlib
import json
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from media_tools import assert_font_glyphs, resolve_font, split_font_spec
from preflight import (
    asr_family,
    check_frame_audit,
    check_package,
    check_red_team,
    check_release_manifest,
    check_translation,
    check_zip,
    load_json,
)


class PreflightTests(unittest.TestCase):
    def test_whisper_variants_share_family(self):
        self.assertEqual(asr_family("openai-whisper"), asr_family("faster-whisper"))

    def test_unknown_engine_is_not_its_own_family(self):
        self.assertEqual(asr_family("invented-engine"), "unknown")

    def test_latin_only_font_is_rejected_for_chinese(self):
        """只含拉丁字形的字体渲中文会得到一排豆腐块，必须在渲染前拦下。

        不能用 resolve_font("latin") 取样：拉丁字体现已优先思源（自带西文，
        中英同族），它本来就有中文字形，拿它当反例测不出这道守卫。
        """
        latin_only = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        sample = next((p for p in latin_only if Path(p).is_file()), None)
        if sample is None:
            self.skipTest("本机没有可用的纯拉丁字体样本")
        with self.assertRaises(SystemExit):
            assert_font_glyphs(sample, "中文金句", "cjk")

    def test_resolved_fonts_cover_what_they_render(self):
        """三处字体各自要覆盖它实际要画的字符，覆盖不了应当抛错而不是画豆腐块。"""
        for kind, sample in (("cjk_bold", "中文金句"),
                             ("cjk_regular", "中文小标"),
                             ("latin", "Bloomberg 2026 0123456789")):
            path, index = split_font_spec(resolve_font(kind))
            assert_font_glyphs(path, sample, kind, index=index)

    def test_load_json_returns_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text('{"ok": true}', encoding="utf-8")
            errors = []
            self.assertEqual(load_json(path, errors, "data"), {"ok": True})
            self.assertEqual(errors, [])

    def test_frame_choice_must_match_spec_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "frame.json"
            path.write_text(json.dumps({
                "heroes": [{"image_id": "img01", "hero_subject": "A", "hero_subject_role": "speaker", "chosen_hero_time": 9, "candidates": list(range(8))}],
                "images": [{"image_id": "img01", "rows": [{"quote_id": "q1", "chosen_frame_time": 8, "candidates": [1, 2, 3, 4, 5]}]}],
            }), encoding="utf-8")
            spec = {"images": [{"id": "img01", "hero_subject": "A", "hero_time": 7, "quotes": [{"quote_id": "q1", "frame_time": 5}]}]}
            errors, passes = [], []
            check_frame_audit(root, path, root / "missing-video", spec, errors, passes)
            self.assertTrue(any("differs from spec" in error for error in errors))
            self.assertTrue(any("not in candidates" in error for error in errors))

    def test_independently_reviewed_frame_may_equal_quote_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "candidate.jpg"
            artifact.write_bytes(b"frame")
            def candidate(second):
                return {"time": second, "artifact": "candidate.jpg",
                        "sha256": hashlib.sha256(b"frame").hexdigest()}
            audit = {
                "heroes": [{"image_id": "img01", "hero_subject": "A",
                             "hero_subject_role": "speaker", "chosen_hero_time": 1.0,
                             "candidates": [candidate(1 + index / 10) for index in range(8)]}],
                "images": [{"image_id": "img01", "rows": [{
                    "quote_id": "q1", "chosen_frame_time": 1.0,
                    "candidates": [candidate(1 + index / 10) for index in range(5)],
                }]}],
            }
            path = root / "frame.json"
            path.write_text(json.dumps(audit), encoding="utf-8")
            spec = {"images": [{"id": "img01", "hero_subject": "A", "hero_time": 1.0,
                                "quotes": [{"quote_id": "q1", "time": 1.0, "frame_time": 1.0}]}]}
            errors, passes = [], []
            check_frame_audit(root, path, root / "missing-video", spec, errors, passes)
            self.assertEqual(errors, [])

    def test_package_requires_actual_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.md"
            path.write_text("人物介绍 首发标题 封面大字 轮播顺序 评论区引导 话题标签 image_id quote_ids 淘汰原因", encoding="utf-8")
            errors, passes = [], []
            check_package(path, {"images": [{"id": "img01", "quotes": [{"quote_id": "q1"}]}]}, errors, passes)
            self.assertIn("package missing image_id value: img01", errors)
            self.assertIn("package missing quote_id value: q1", errors)

    def test_stop_and_empty_calibration_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = {"images": [{"quotes": [{
                "quote_id": "q1", "source_en": "hello", "cn": "你好世界完整译文", "time": 1.0,
            }]}]}
            payloads = {
                0: {"status": "complete", "segment_count": 1, "missing_count": 0,
                    "rows": [{"quote_id": "q1", "source_en": "hello", "second_source": "", "severity": ""}]},
                1: {"rows": [{"quote_id": "q1", "source_en": "hello", "current_cn": "你好世界完整译文",
                                "checks": {}, "adjudication": "stop", "changed": False}]},
                2: {"rows": [{"quote_id": "q1", "source_en": "hello", "current_cn": "你好世界完整译文",
                                "diff": {}, "adjudication": "retain", "changed": False}]},
                3: {"rows": [{"quote_id": "q1", "source_en": "hello", "current_cn": "你好世界完整译文",
                                "claims": {}, "evidence_basis": [], "adjudication": "stop", "changed": False}]},
            }
            rounds = []
            for number, payload in payloads.items():
                path = root / f"r{number}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                rounds.append({"round": number, "status": "completed", "artifact": path.name})
            audit = {"primary_source_engine": "invented-primary",
                     "second_source_engine": "invented-secondary",
                     "independent_architecture": True, "rounds": rounds}
            errors, warnings, passes = [], [], []
            check_translation(root, audit, spec, root / "r0.json", root / "missing.srt",
                              root / "missing-video", "final", errors, warnings, passes)
            self.assertTrue(any("stop adjudication blocks delivery" in error for error in errors))
            self.assertTrue(any("recognized ASR architecture" in error for error in errors))

    def test_red_team_stop_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "red.json"
            path.write_text(json.dumps({"status": "completed", "rows": [{
                "quote_id": "q1", "risk_tags": ["numbers"], "challenge": "check",
                "decision": "stop", "reviewer": "r", "reviewed_at": "2026-01-01T00:00:00Z",
            }]}), encoding="utf-8")
            spec = {"meta": {"risk_flags": ["numbers"]},
                    "images": [{"quotes": [{"quote_id": "q1", "cn": "文本"}]}]}
            errors, passes = [], []
            check_red_team(root, spec, path, "final", errors, passes)
            self.assertTrue(any("stop decision blocks delivery" in error for error in errors))

    def test_minimal_manifest_and_extra_zip_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "only.txt"
            artifact.write_text("only", encoding="utf-8")
            release = root / "release.zip"
            with zipfile.ZipFile(release, "w") as zf:
                zf.write(artifact, "only.txt")
                zf.writestr("extra.txt", "extra")
            manifest_data = {
                "version": "1", "status": "final", "image_count": 1, "quote_count": 1,
                "branding_mode": "none", "manifest_path": "audit/release_manifest.json",
                "artifact_hashes": {"only.txt": hashlib.sha256(b"only").hexdigest()},
                "package_members": ["only.txt", "audit/release_manifest.json"],
                "release_zip": "release.zip",
            }
            manifest = root / "audit/release_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
            errors, passes = [], []
            check_release_manifest(root, manifest, {"images": [{"quotes": [{}]}]},
                                   "final", errors, passes)
            check_zip(release, root, manifest_data, errors, passes)
            self.assertTrue(any("missing mandatory artifact hashes" in error for error in errors))
            self.assertTrue(any("ZIP member set differs" in error for error in errors))

    def test_duplicate_and_symlink_zip_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release.zip"
            symlink = zipfile.ZipInfo("link")
            symlink.create_system = 3
            symlink.external_attr = 0o120777 << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(release, "w") as zf:
                    zf.writestr("only.txt", "first")
                    zf.writestr("only.txt", "second")
                    zf.writestr(symlink, "target")
            manifest = {
                "manifest_path": "manifest.json",
                "artifact_hashes": {"only.txt": hashlib.sha256(b"first").hexdigest()},
                "package_members": ["only.txt", "link"],
            }
            errors, passes = [], []
            check_zip(release, root, manifest, errors, passes)
            self.assertTrue(any("duplicate member" in error for error in errors))
            self.assertTrue(any("symbolic links" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
