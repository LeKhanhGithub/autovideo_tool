from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_video import Cue, Word, align_words_to_source, write_srt


class AlignmentTests(unittest.TestCase):
    def test_ignores_extra_edge_token(self) -> None:
        result = align_words_to_source(
            [Word("Hello", 0.0, 0.3), Word("EXTRA", 0.3, 0.5), Word("world", 0.5, 0.8)],
            "Hello world.",
        )
        self.assertEqual([word.text for word in result], ["Hello", "world."])
        self.assertEqual((result[1].start, result[1].end), (0.5, 0.8))

    def test_interpolates_missing_edge_token(self) -> None:
        result = align_words_to_source(
            [Word("Hello", 0.0, 0.3), Word("world", 0.5, 0.8)],
            "Hello missing world.",
        )
        self.assertEqual([word.text for word in result], ["Hello", "missing", "world."])
        self.assertEqual((result[1].start, result[1].end), (0.3, 0.5))

    def test_srt_holds_cue_until_next_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "test.srt"
            write_srt([Cue("First", 0.0, 1.0), Cue("Second", 1.5, 2.0)], output)
            content = output.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,500", content)
        self.assertIn("00:00:01,500 --> 00:00:02,000", content)


if __name__ == "__main__":
    unittest.main()
