from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from image_layouts import _display_heading, _fit_split_heading
from novel_video import (
    Cue,
    Word,
    align_words_to_source,
    prepare_text_for_tts,
    prepare_text_for_tts_with_report,
    synchronize_scene_durations,
    write_srt,
)
from story_visuals import build_cue_storyboard, build_source_line_storyboard, build_storyboard


class AlignmentTests(unittest.TestCase):
    def test_split_heading_deduplicates_chapter_and_stays_in_reserved_width(self) -> None:
        heading = (
            'Chapter 35: Chapter 35: "Farming Glorifies the Clan, '
            'Pig-Raising Honors the Ancestors.'
        )
        self.assertEqual(
            _display_heading(heading),
            "Chapter 35: Farming Glorifies the Clan, Pig-Raising Honors the Ancestors.",
        )
        draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
        lines, font, _line_height = _fit_split_heading(draw, heading)
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(lines)
        self.assertTrue(all(draw.textbbox((0, 0), line, font=font)[2] <= 760 for line in lines))

    def test_attribute_counts_are_expanded_for_audio_only(self) -> None:
        source = "English*9\nDropped Strength*2, Speed * 6.\nCrystal (Tier 1)*1\nBiology*15"
        spoken = prepare_text_for_tts(source)
        self.assertEqual(
            spoken,
            "English times 9\nDropped Strength times 2, Speed times 6.\n"
            "Crystal (Tier 1) times 1\nBiology times 15",
        )
        self.assertEqual(
            source,
            "English*9\nDropped Strength*2, Speed * 6.\nCrystal (Tier 1)*1\nBiology*15",
        )

    def test_audio_omits_markdown_and_trailing_format_asterisks(self) -> None:
        source = "Use *emphasis* here.\nDamage*9 bonus points.\nValue 0.2*."
        self.assertEqual(
            prepare_text_for_tts(source),
            "Use emphasis here.\nDamage times 9 bonus points.\nValue 0.2.",
        )

    def test_masked_words_are_spoken_intelligibly(self) -> None:
        source = 'What the f**k! That b*stard said D*mn, b*tch, a**, a*s and F*ck.'
        spoken = prepare_text_for_tts(source)
        self.assertEqual(
            spoken,
            'What the F-word! That bastard said damn, bitch, ass, ass and F-word.',
        )

    def test_numeric_symbols_and_units_are_expanded_for_audio(self) -> None:
        source = "HP: 10/300. Online 24/7 at 12.7m/s. XP +20. A+-level. Chance 39.5%."
        self.assertEqual(
            prepare_text_for_tts(source),
            "HP: 10 out of 300. Online 24 7 at 12.7 meters per second. "
            "XP plus 20. A plus level. Chance 39.5 percent.",
        )

    def test_display_brackets_and_visual_only_symbols_are_omitted_from_audio(self) -> None:
        source = "[Farmland upgraded.] 「One hour later.」 An inverted T (⊥). o(╯□╰)o…"
        spoken, report = prepare_text_for_tts_with_report(source)
        self.assertEqual(spoken, "Farmland upgraded. One hour later. An inverted T.…")
        self.assertEqual(source, "[Farmland upgraded.] 「One hour later.」 An inverted T (⊥). o(╯□╰)o…")
        self.assertFalse(report["display_text_changed"])
        self.assertEqual(report["needs_review"], [])

    def test_unknown_symbol_is_flagged_for_review_without_changing_source(self) -> None:
        source = "Reward: 3€."
        spoken, report = prepare_text_for_tts_with_report(source)
        self.assertEqual(spoken, source)
        self.assertEqual(report["needs_review"][0]["character"], "€")

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
