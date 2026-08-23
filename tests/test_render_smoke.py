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

from media_tools import ffmpeg_exe


class RenderSmokeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
    def test_renderer_outputs_image_and_reproducibility_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "source.mp4"
            subprocess.run(
                [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)],
                check=True,
            )
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "meta": {"kicker": "人物访谈", "footer": "Source 2026"},
                "images": [{"id": "img01", "title": "测试标题", "hero_time": 0.5,
                            "quotes": [{"quote_id": "q1", "time": 0.5, "frame_time": 0.7,
                                        "cn": "这是完整中文金句", "en": "A verified quote"}]}],
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "images"
            render = root / "render.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/render_quote_cards.py"), str(video),
                 "--spec", str(spec), "--out-dir", str(output), "--render-json", str(render),
                 "--source-subtitle-policy", "verified-absent"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            image = next(output.glob("0*.jpg"))
            with Image.open(image) as opened:
                self.assertEqual(opened.size, (1440, 1920))
            metadata = json.loads(render.read_text(encoding="utf-8"))
            self.assertEqual(set(metadata["font_sha256"]), {"cjk_bold", "cjk_regular", "latin"})
            self.assertIn("renderer_sha256", metadata)
            self.assertGreaterEqual(len(metadata["config"]), 10)


if __name__ == "__main__":
    unittest.main()
