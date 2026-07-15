from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_video import Cue, Word, align_words_to_source, synchronize_scene_durations, write_srt
from story_visuals import build_cue_storyboard, build_source_line_storyboard, build_storyboard


class AlignmentTests(unittest.TestCase):
    def test_storyboard_covers_duration_and_uses_story_text(self) -> None:
        text = "The dragon entered the frozen castle. Mira raised her silver sword. The gate collapsed behind them."
        scenes = build_storyboard(text, 31, scene_seconds=10)
        self.assertEqual(len(scenes), 4)
        self.assertAlmostEqual(sum(scene.duration for scene in scenes), 31)
        self.assertIn("dragon", scenes[0].excerpt.casefold())
        self.assertTrue(all(scene.style == "story" for scene in scenes))

    def test_cue_storyboard_groups_consecutive_sentences(self) -> None:
        cues = [Cue("First sentence.", 0, 2), Cue("Active sentence.", 2, 4), Cue("Next sentence.", 4, 6)]
        scenes = build_cue_storyboard(cues, 6, target_seconds=10)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0].lines, ["First sentence.", "Active sentence.", "Next sentence."])
        self.assertEqual(scenes[0].excerpt, "First sentence. Active sentence. Next sentence.")

    def test_source_storyboard_preserves_txt_lines_verbatim(self) -> None:
        source = "Donghai No. 1 High School. 5.30 pm.\nRing, ring, ring..."
        tokens = ["Donghai", "No.", "1", "High", "School.", "5.", "30", "pm.", "Ring,", "ring,", "ring..."]
        words = [Word(token, index * 0.2, (index + 1) * 0.2) for index, token in enumerate(tokens)]
        scenes = build_source_line_storyboard(source, words, 3, target_seconds=10)
        self.assertEqual(scenes[0].lines[0], "Donghai No. 1 High School. 5.30 pm.")
        self.assertEqual(scenes[0].lines[1], "Ring, ring, ring...")
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

    def test_scene_transitions_match_absolute_word_starts(self) -> None:
        source = "First line.\nSecond line.\nThird line."
        words = [
            Word("First", 0.125, 0.4), Word("line.", 0.4, 1.0),
            Word("Second", 1.75, 2.0), Word("line.", 2.0, 2.6),
            Word("Third", 3.5, 3.8), Word("line.", 3.8, 4.4),
        ]
        scenes = build_source_line_storyboard(source, words, 5.0, target_seconds=0.5)
        synchronize_scene_durations(scenes, 5.0)
        transitions = [0.0]
        for scene in scenes[:-1]:
            transitions.append(transitions[-1] + scene.duration)
        self.assertEqual(len(transitions), len(scenes))
        for actual, scene in zip(transitions[1:], scenes[1:]):
            self.assertAlmostEqual(actual, scene.start, places=6)


if __name__ == "__main__":
    unittest.main()
