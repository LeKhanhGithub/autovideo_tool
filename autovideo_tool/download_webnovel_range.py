from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


@dataclass(frozen=True)
class ChapterLink:
    number: int
    title: str
    chapter_id: str
    url: str


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def validate_book_url(book_url: str) -> str:
    parsed = urlparse(book_url)
    if parsed.scheme != "https" or parsed.hostname not in {"webnovel.com", "www.webnovel.com"}:
        raise ValueError("--book-url phải là URL HTTPS chính thức trên www.webnovel.com.")
    match = re.search(r"_(\d+)$", parsed.path.rstrip("/"))
    if not match:
        raise ValueError("Không tìm thấy WebNovel book ID ở cuối --book-url.")
    return match.group(1)


def parse_catalog(soup: BeautifulSoup, base_url: str) -> dict[int, ChapterLink]:
    chapters: dict[int, ChapterLink] = {}
    for item in soup.select("li[data-cid]"):
        number_node = item.select_one("i._num")
        anchor = item.select_one("a[href]")
        if number_node is None or anchor is None:
            continue
        number_text = number_node.get_text(" ", strip=True)
        if not number_text.isdigit():
            continue
        number = int(number_text)
        chapter_id = str(item.get("data-cid", "")).strip()
        title = str(anchor.get("title") or anchor.get_text(" ", strip=True)).strip()
        if not chapter_id or not title:
            continue
        chapters.setdefault(
            number,
            ChapterLink(number, title, chapter_id, urljoin(base_url, str(anchor["href"]))),
        )
    return chapters


def parse_chapter(soup: BeautifulSoup, expected: ChapterLink) -> tuple[str, list[str]]:
    chapter = soup.select_one(".chapter_content")
    words = chapter.select_one(".cha-words") if chapter else None
    if chapter is None or words is None:
        raise RuntimeError(f"Chapter {expected.number} không có nội dung công khai để tải.")
    if chapter.select_one(".cha-content._lock") or any(
        "j_lock_chap_" in " ".join(node.get("class", []))
        for node in soup.select(".chapter_content")
    ):
        raise RuntimeError(
            f"Chapter {expected.number} đang bị khóa; downloader từ chối ghi bản preview thiếu."
        )

    title_node = chapter.select_one(".cha-tit")
    page_title = title_node.get_text(" ", strip=True) if title_node else ""
    title_match = re.search(rf"Chapter\s+{expected.number}\s*:\s*(.*?)(?:\s+Editor:|$)", page_title, re.I)
    title = title_match.group(1).strip() if title_match else expected.title
    title = re.sub(rf"^Chapter\s+{expected.number}\s*:\s*", "", title, flags=re.IGNORECASE)

    paragraphs = []
    nodes = words.select(".cha-paragraph p") or words.select("p")
    for node in nodes:
        value = re.sub(r"[ \t]+", " ", node.get_text(" ", strip=True)).strip()
        if value:
            paragraphs.append(value)
    if not paragraphs:
        raise RuntimeError(f"Chapter {expected.number} không trích được đoạn văn nào.")
    return title, paragraphs


def download_range(
    book_url: str,
    chapter_start: int,
    chapter_end: int,
    output: Path,
) -> tuple[str, dict[str, object]]:
    book_id = validate_book_url(book_url)
    catalog_url = f"https://www.webnovel.com/book/{book_id}/catalog"
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})

    catalog = parse_catalog(fetch_soup(session, catalog_url), book_url)
    missing = [number for number in range(chapter_start, chapter_end + 1) if number not in catalog]
    if missing:
        raise RuntimeError(f"Catalog thiếu chapter: {missing}")

    blocks: list[str] = []
    chapter_manifest: list[dict[str, object]] = []
    for number in range(chapter_start, chapter_end + 1):
        link = catalog[number]
        title, paragraphs = parse_chapter(fetch_soup(session, link.url), link)
        block = "\n\n".join([f"Chapter {number}: {title}", *paragraphs])
        blocks.append(block)
        chapter_manifest.append(
            {
                "number": number,
                "title": title,
                "chapter_id": link.chapter_id,
                "url": link.url,
                "paragraphs": len(paragraphs),
                "characters": len(block),
            }
        )
        print(f"Downloaded Chapter {number}: {title}", flush=True)

    text = "\n\n".join(blocks) + "\n"
    manifest: dict[str, object] = {
        "source_name": "WebNovel",
        "source_type": "official_licensed",
        "book_url": book_url,
        "catalog_url": catalog_url,
        "book_id": book_id,
        "chapter_start": chapter_start,
        "chapter_end": chapter_end,
        "chapter_count": len(chapter_manifest),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "usage_note": "Fetched from publicly readable official pages; usage remains subject to WebNovel terms.",
        "chapters": chapter_manifest,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    temp_manifest = output.with_suffix(".source.json.tmp")
    manifest_output = output.with_suffix(".source.json")
    temp_output.write_text(text, encoding="utf-8")
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_output.replace(output)
    temp_manifest.replace(manifest_output)
    return text, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a public chapter range from official WebNovel pages.")
    parser.add_argument("--book-url", required=True)
    parser.add_argument("--chapter-start", type=int, required=True)
    parser.add_argument("--chapter-end", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--confirm-rights",
        action="store_true",
        help="Confirm that you may download/use these publicly readable chapters.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.confirm_rights:
        raise SystemExit("Cần --confirm-rights trước khi tải nội dung.")
    if args.chapter_start < 1 or args.chapter_end < args.chapter_start:
        raise SystemExit("Khoảng chapter không hợp lệ.")
    text, manifest = download_range(
        args.book_url,
        args.chapter_start,
        args.chapter_end,
        args.output.expanduser().resolve(),
    )
    print(
        f"Done: chapters={manifest['chapter_count']} chars={len(text)} "
        f"sha256={manifest['text_sha256']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
