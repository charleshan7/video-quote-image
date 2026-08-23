import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from asr_crosscheck import norm


class AsrCrosscheckTests(unittest.TestCase):
    def test_compound_number_words_match_numeric_form(self):
        self.assertEqual(norm("twenty five people"), ["25", "people"])
        self.assertEqual(norm("one hundred and five"), ["105"])

    def test_apostrophes_do_not_hide_negation_tokens(self):
        self.assertEqual(norm("can't"), ["cant"])


if __name__ == "__main__":
    unittest.main()
