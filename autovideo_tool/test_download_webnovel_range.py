from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from download_webnovel_range import ChapterLink, parse_chapter


class WebNovelParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.link = ChapterLink(33, "Chapter 33: Long Title", "123", "https://www.webnovel.com/test")

    def test_deduplicates_chapter_prefix_from_official_title(self) -> None:
        soup = BeautifulSoup(
            """
            <div class="chapter_content">
              <div class="cha-tit">Chapter 33: Chapter 33: Long Title</div>
              <div class="cha-content"><div class="cha-words">
                <div class="cha-paragraph"><p>First paragraph.</p></div>
                <div class="cha-paragraph"><p>Second paragraph.</p></div>
              </div></div>
            </div>
            """,
            "html.parser",
        )
        title, paragraphs = parse_chapter(soup, self.link)
        self.assertEqual(title, "Long Title")
        self.assertEqual(paragraphs, ["First paragraph.", "Second paragraph."])

    def test_rejects_locked_preview_content(self) -> None:
        soup = BeautifulSoup(
            """
            <div class="chapter_content j_lock_chap_123">
              <div class="cha-tit">Chapter 33: Long Title</div>
              <div class="cha-content _lock"><div class="cha-words">
                <div class="cha-paragraph"><p>Short preview.</p></div>
              </div></div>
            </div>
            """,
            "html.parser",
        )
        with self.assertRaisesRegex(RuntimeError, "đang bị khóa"):
            parse_chapter(soup, self.link)


if __name__ == "__main__":
    unittest.main()
