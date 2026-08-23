import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from locate_quotes import build_index, find_cue, load_cues


class LocateQuotesTests(unittest.TestCase):
    def test_webvtt_mmss_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.vtt"
            path.write_text(
                "WEBVTT\n\ncue-1\n00:01.000 --> 00:04.000 align:start position:0%\nHello <b>world</b>!\n",
                encoding="utf-8",
            )
            cues = load_cues(path)
            self.assertEqual((cues[0].start, cues[0].end, cues[0].text), (1.0, 4.0, "hello world"))

    def test_two_phrases_in_same_cue_keep_same_source_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subs = tmp / "sample.srt"
            subs.write_text("1\n00:00:01,000 --> 00:00:04,000\nAlpha beta gamma delta\n", encoding="utf-8")
            quotes = tmp / "quotes.json"
            quotes.write_text(json.dumps({"images": [{
                "id": "img01", "title": "test", "quotes": [
                    {"quote_id": "q1", "match": "Alpha beta", "en": "Alpha beta", "cn": "甲"},
                    {"quote_id": "q2", "match": "gamma delta", "en": "gamma delta", "cn": "乙"},
                ]
            }]}), encoding="utf-8")
            out = tmp / "spec.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/locate_quotes.py"), str(subs), str(quotes), "-o", str(out)], check=True)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual([q["time"] for q in data["images"][0]["quotes"]], [1.0, 1.0])
            self.assertEqual([q["quote_id"] for q in data["images"][0]["quotes"]], ["q1", "q2"])

    def test_failed_lookup_does_not_replace_existing_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subs = tmp / "sample.srt"
            subs.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello world\n", encoding="utf-8")
            quotes = tmp / "quotes.json"
            quotes.write_text(json.dumps({"images": [{"id": "i", "title": "t", "quotes": [
                {"quote_id": "q", "match": "missing phrase", "en": "", "cn": ""}
            ]}]}), encoding="utf-8")
            out = tmp / "spec.json"
            out.write_text('{"sentinel": true}', encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/locate_quotes.py"), str(subs), str(quotes), "-o", str(out)], capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), {"sentinel": True})

    def test_cross_cue_match_maps_to_first_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.srt"
            path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:03,000\nworld\n", encoding="utf-8")
            cues = load_cues(path)
            flat, index = build_index(cues)
            self.assertEqual(find_cue(flat, index, "hello world").start, 1.0)

    def test_cross_cue_output_records_last_cue_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subs = tmp / "sample.srt"
            subs.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:03,500\nworld\n", encoding="utf-8")
            quotes = tmp / "quotes.json"
            quotes.write_text(json.dumps({"images": [{"id": "i", "title": "t", "quotes": [
                {"quote_id": "q", "match": "hello world", "en": "", "cn": ""}
            ]}]}), encoding="utf-8")
            out = tmp / "spec.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/locate_quotes.py"),
                            str(subs), str(quotes), "-o", str(out)], check=True)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["images"][0]["quotes"][0]["cue_end"], 3.5)

    def test_ambiguous_repeated_phrase_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subs = tmp / "sample.srt"
            subs.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n2\n00:00:05,000 --> 00:00:06,000\nHello world\n", encoding="utf-8")
            quotes = tmp / "quotes.json"
            quotes.write_text(json.dumps({"images": [{"id": "i", "title": "t", "quotes": [
                {"quote_id": "q", "match": "hello world", "en": "", "cn": ""}
            ]}]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/locate_quotes.py"),
                                     str(subs), str(quotes), "-o", str(tmp / "spec.json")],
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("occurrence", result.stderr)

    def test_occurrence_selects_requested_repeated_phrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subs = tmp / "sample.srt"
            subs.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n2\n00:00:05,000 --> 00:00:06,000\nHello world\n", encoding="utf-8")
            quotes = tmp / "quotes.json"
            quotes.write_text(json.dumps({"images": [{"id": "i", "title": "t", "quotes": [
                {"quote_id": "q", "match": "hello world", "occurrence": 2, "en": "", "cn": ""}
            ]}]}), encoding="utf-8")
            out = tmp / "spec.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/locate_quotes.py"),
                            str(subs), str(quotes), "-o", str(out)], check=True)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["images"][0]["quotes"][0]["time"], 5.0)

    def test_raw_subtitle_case_is_preserved_for_proper_nouns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.srt"
            path.write_text("1\n00:00:01,000 --> 00:00:02,000\nAlice visited Paris\n", encoding="utf-8")
            cue = load_cues(path)[0]
            self.assertEqual(cue.text, "alice visited paris")
            self.assertEqual(cue.raw_text, "Alice visited Paris")


if __name__ == "__main__":
    unittest.main()
