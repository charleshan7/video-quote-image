import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from media_tools import ffmpeg_exe, resolve_font, split_font_spec


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class PreflightIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
    def test_valid_final_package_passes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            video = project / "source/source.mp4"
            video.parent.mkdir()
            subprocess.run(
                [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=3",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                 "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)],
                check=True,
            )
            info = write_json(project, "source/source.info.json", {"id": "source-id"})
            write_json(project, "source/source_download.json", {
                "source_url": "https://example.com/source", "webpage_url": "https://example.com/source",
                "extractor": "test", "source_id": "source-id", "downloaded_at": "2026-01-01T00:00:00Z",
                "yt_dlp_version": "test", "download_mode": "direct",
                "format_selector": "bestvideo*+bestaudio/best", "quality_scope": "best_visible_to_yt_dlp",
                "best_visible_to_yt_dlp": True, "quality_evidence": "test fixture",
                "configuration_scope": "--ignore-config", "media_path": "source.mp4",
                "file_sha256": sha256(video), "info_json_path": "source.info.json",
                "info_json_sha256": sha256(info),
                "video_streams": [{"codec_type": "video"}], "audio_streams": [{"codec_type": "audio"}],
                "yt_dlp_format_id": "v+a", "yt_dlp_requested_formats": [{"format_id": "v"}],
            })
            spec = {"meta": {"risk_flags": [], "footer": "Source"}, "images": [{
                "id": "img01", "title": "Test", "hero_time": 1.0,
                "hero_subject_id": "person-01", "hero_subject": "Alice",
                "hero_subject_role": "speaker", "hero_subject_source_url": "https://example.com/alice",
                "hero_subject_source_quote": "Alice is the speaker", "hero_subject_confidence": 0.9,
                "structure": "assertion", "core_quote_index": 0,
                "quotes": [{"quote_id": "q1", "time": 1.0, "frame_time": 1.0,
                            "match": "hello world", "source_en": "hello world",
                            "en": "hello world", "cn": "这是完整中文金句"}],
            }]}
            write_json(project, "audit/spec.json", spec)
            write_json(project, "audit/quotes.json", {"images": [{
                "id": "img01", "title": "Test", "quotes": [{
                    "quote_id": "q1", "match": "hello world", "en": "hello world", "cn": "这是完整中文金句",
                }],
            }]})
            write_json(project, "audit/selection_audit.json", {"images": [{
                "id": "img01", "structure": "assertion", "planned_count": 1, "actual_count": 1,
                "core_quote_index": 0, "rejected_quotes": [], "count_reason": "one complete claim",
            }]})
            subs = project / "audit/source_subs.srt"
            subs.write_text("1\n00:00:00,500 --> 00:00:01,500\nhello world\n", encoding="utf-8")

            primary = {"name": "youtube-auto/google-asr", "model": "captions",
                       "version": "test", "family": "google-asr"}
            secondary = {"name": "elevenlabs", "model": "scribe_v2",
                         "version": "test", "family": "elevenlabs-scribe"}
            asr = {
                "status": "complete", "source_video_sha256": sha256(video),
                "subtitles_sha256": sha256(subs), "primary_engine": primary,
                "second_engine": secondary, "transcript_provenance_verified": True,
                "segment_count": 1, "missing_count": 0,
                "segments": [{"quote_id": "q1", "quote_time": 1.0,
                              "wav_sha256": "a" * 64, "transcript_sha256": "b" * 64,
                              "result_present": True}],
                "rows": [{"quote_id": "q1", "source_en": "hello world",
                          "second_source": "hello world", "severity": "none"}],
            }
            write_json(project, "audit/review_asr_xcheck.json", asr)
            r1 = {"round": 1, "status": "completed", "artifact": "audit/round1_self_check.json",
                  "quote_count": 1, "rows": [{"quote_id": "q1", "source_en": "hello world",
                  "current_cn": "这是完整中文金句", "checks": {key: "pass" for key in
                  ["subject", "person", "negation", "quantity", "scope", "causality", "tone", "terms"]},
                  "adjudication": "retain", "changed": False}]}
            r2 = {"round": 2, "status": "completed", "artifact": "audit/round2_mechanical_diff.json",
                  "quote_count": 1, "rows": [{"quote_id": "q1", "source_en": "hello world",
                  "current_cn": "这是完整中文金句", "diff": {key: "same" for key in
                  ["subject", "negation", "quantity", "modality", "scope", "terms", "causality"]},
                  "adjudication": "retain", "changed": False}]}
            r3 = {"round": 3, "status": "completed", "artifact": "audit/round3_adjudication.json",
                  "quote_count": 1, "rows": [{"quote_id": "q1", "source_en": "hello world",
                  "current_cn": "这是完整中文金句",
                  "evidence_basis": ["round0_asr", "round1_self_check", "round2_mechanical_diff"],
                  "claims": {"subject": "speaker", "negation": "none", "quantity": "none",
                             "modality": "statement", "scope": "sentence", "terms": [],
                             "causality": "none", "source_time": 1.0},
                  "adjudication": "retain", "changed": False}]}
            write_json(project, "audit/round1_self_check.json", r1)
            write_json(project, "audit/round2_mechanical_diff.json", r2)
            write_json(project, "audit/round3_adjudication.json", r3)
            write_json(project, "audit/translation_audit.json", {
                "primary_source_engine": primary["name"], "second_source_engine": secondary["name"],
                "independent_architecture": True,
                "rounds": [{"round": 0, "status": "completed", "artifact": "audit/review_asr_xcheck.json"},
                           {"round": 1, "status": "completed", "artifact": "audit/round1_self_check.json"},
                           {"round": 2, "status": "completed", "artifact": "audit/round2_mechanical_diff.json"},
                           {"round": 3, "status": "completed", "artifact": "audit/round3_adjudication.json"}],
            })
            write_json(project, "audit/people.json", {"people": [{
                "person_id": "person-01", "name": "Alice", "person_type": "speaker",
                "role": "speaker", "source_url": "https://example.com/alice",
                "source_quote": "Alice is the speaker", "verified_at": "2026-01-01T00:00:00Z",
                "confidence": 0.9,
            }]})

            evidence_image = project / "audit/evidence.jpg"
            evidence_image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 64), "green").save(evidence_image)
            evidence_hash = sha256(evidence_image)
            def candidate(second, index):
                path = project / f"audit/frames/candidate-{index:02d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(evidence_image.read_bytes())
                return {"time": second, "artifact": str(path.relative_to(project)), "sha256": evidence_hash}
            hero_candidates = [candidate(0.2 + index * 0.2, index) for index in range(8)]
            quote_candidates = [candidate(0.6 + index * 0.2, 20 + index) for index in range(5)]
            write_json(project, "audit/frame_audit.json", {
                "source_video_sha256": sha256(video), "reviewer": "tester",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "heroes": [{"image_id": "img01", "hero_subject": "Alice", "hero_subject_role": "speaker",
                            "chosen_hero_time": 1.0, "chosen_reason": "clear",
                            "candidates": hero_candidates}],
                "images": [{"image_id": "img01", "rows": [{"quote_id": "q1",
                            "chosen_frame_time": 1.0, "chosen_reason": "clear",
                            "candidates": quote_candidates}]}],
            })
            samples = []
            for index, second in enumerate([0.5, 1.5, 2.5], 1):
                source = project / f"audit/subtitle_samples/{index}-source.jpg"
                processed = project / f"audit/subtitle_samples/{index}-processed.jpg"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(evidence_image.read_bytes())
                processed.write_bytes(evidence_image.read_bytes())
                samples.append({"time": second, "source_artifact": str(source.relative_to(project)),
                                "source_sha256": evidence_hash,
                                "processed_artifact": str(processed.relative_to(project)),
                                "processed_sha256": evidence_hash, "decision": "absent"})
            write_json(project, "audit/subtitle_audit.json", {
                "source_video_sha256": sha256(video), "policy": "verified-absent", "crop_bottom": 0,
                "reviewer": "tester", "reviewed_at": "2026-01-01T00:00:00Z", "samples": samples,
            })

            output = project / "images/01_test.jpg"
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1440, 1920), "black").save(output)
            Image.new("RGB", (360, 480), "black").save(project / "images/final_contact_sheet.jpg")
            # 证据里的字体值可能带 "::face序号"（macOS 的 ttc 候选就是这样），
            # 门禁必须拆开再查文件；这里显式带上后缀，让这条路径一直被测到。
            fonts = {name: f"{split_font_spec(resolve_font(name))[0]}::0"
                     for name in ["cjk_bold", "cjk_regular", "latin"]}
            write_json(project, "audit/render.json", {
                "width": 1440, "height": 1920, "source_subtitle_policy": "verified-absent",
                "source_crop_bottom": 0, "fonts": fonts,
                "font_sha256": {name: sha256(split_font_spec(spec)[0])
                                for name, spec in fonts.items()},
                "renderer_sha256": sha256(ROOT / "scripts/render_quote_cards.py"),
                "config": {str(index): index for index in range(10)},
                "spec_sha256": sha256(project / "audit/spec.json"),
                "source_video_sha256": sha256(video),
                "outputs": [{"image_id": "img01", "filename": output.name, "sha256": sha256(output)}],
                "warnings": [],
            })
            (project / "xiaohongshu_package.md").write_text(
                "人物介绍 首发标题 封面大字 轮播顺序 评论区引导 话题标签 "
                "image_id img01 quote_ids q1 淘汰原因", encoding="utf-8"
            )
            brand = subprocess.run(
                [sys.executable, str(ROOT / "scripts/add_brand.py"), str(output),
                 "--out", str(project / "branded/01_test.jpg"),
                 "--spec", str(project / "audit/spec.json"),
                 "--render", str(project / "audit/render.json"),
                 "--metadata", str(project / "audit/brand/01_test.json")],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(brand.returncode, 0, brand.stderr)

            package = subprocess.run(
                [sys.executable, str(ROOT / "scripts/package_release.py"), "--root", str(project),
                 "--status", "final", "--version", "v1", "--zip", "../release.zip",
                 "--branding", "required"], capture_output=True, text=True, check=False,
            )
            self.assertEqual(package.returncode, 0, package.stderr)
            preflight = subprocess.run(
                [sys.executable, str(ROOT / "scripts/preflight.py"), "--root", str(project),
                 "--video", "source/source.mp4", "--status", "final", "--zip", "../release.zip",
                 "--min-images", "1", "--max-images", "1", "--cn-min", "1", "--cn-max", "30",
                 "--no-report"], capture_output=True, text=True, check=False,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            self.assertEqual(json.loads(preflight.stdout)["status"], "FINAL_ALLOWED")


if __name__ == "__main__":
    unittest.main()
