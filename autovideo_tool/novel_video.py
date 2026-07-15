from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import edge_tts
import requests
from bs4 import BeautifulSoup
from image_layouts import render_image_layout
from story_visuals import build_cue_storyboard, build_source_line_storyboard, build_storyboard, render_storyboard


DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


@dataclass
class Word:
    text: str
    start: float
    end: float
    break_after: bool = False


@dataclass
class Cue:
    text: str
    start: float
    end: float


def normalize_text(text: str) -> str:
    text = html.unescape(text).replace("\u200b", " ").replace("\ufeff", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        line = re.sub(r"(?<=[.!?'\"”’])\s+[12]$", "", line)
        if re.match(r"^Chapter\s+\d+:", line, re.IGNORECASE) and not re.search(r"\bLevel\s+[12]$", line):
            line = re.sub(r"\s+[12]$", "", line)
        cleaned.append(line)
    return "\n".join(line for line in cleaned if line)


def fetch_url(url: str, timeout: int = 30) -> tuple[str, str]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "Web novel").strip()

    selectors = (
        ".cha-words",
        ".chapter_content",
        ".chapter-content",
        "article",
        "[itemprop='articleBody']",
    )
    candidates: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            value = normalize_text(node.get_text("\n", strip=True))
            if value:
                candidates.append(value)

    if not candidates:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (TypeError, json.JSONDecodeError):
                continue
            candidates.extend(find_json_text(data))

    content = max(candidates, key=len, default="")
    if len(content) < 80:
        raise RuntimeError(
            "Trang không cung cấp nội dung chương cho trình tải tự động. "
            "Hãy lưu chương thành TXT rồi chạy với --text-file."
        )
    return title, content


def find_json_text(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"articlebody", "text", "content", "chaptercontent"} and isinstance(child, str):
                cleaned = normalize_text(BeautifulSoup(child, "html.parser").get_text("\n"))
                if len(cleaned) >= 80:
                    found.append(cleaned)
            else:
                found.extend(find_json_text(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_json_text(child))
    return found


def split_for_tts(text: str, max_chars: int = 1800) -> list[str]:
    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks: list[str] = []
    current = ""
    for unit in (u.strip() for u in units if u.strip()):
        parts = [unit[i : i + max_chars] for i in range(0, len(unit), max_chars)]
        for part in parts:
            candidate = f"{current}\n{part}".strip() if current else part
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def restore_source_tokens(words: list[Word], source: str) -> list[Word]:
    """Restore source capitalization and punctuation removed by Edge boundaries."""
    source_matches = list(re.finditer(r"\S+", source))
    source_tokens = [match.group() for match in source_matches]

    def comparable(value: str) -> str:
        return re.sub(r"[^\w']+", "", value, flags=re.UNICODE).casefold()

    cursor = 0
    restored: list[Word] = []
    for word in words:
        wanted = comparable(word.text)
        selected = word.text
        matched = False
        for index in range(cursor, min(cursor + 5, len(source_tokens))):
            for span in range(1, min(4, len(source_tokens) - index) + 1):
                end_index = index + span
                combined = " ".join(source_tokens[index:end_index])
                if comparable(combined) == wanted:
                    selected = combined
                    cursor = end_index
                    next_start = source_matches[end_index].start() if end_index < len(source_matches) else len(source)
                    break_after = "\n" in source[source_matches[end_index - 1].end() : next_start]
                    matched = True
                    break
            if matched:
                break
        else:
            break_after = False
        restored.append(Word(selected, word.start, word.end, break_after))
    return restored


LEXICAL_RE = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)


def align_words_to_source(words: list[Word], source: str) -> list[Word]:
    """Globally align timed Edge events to source tokens and restore all punctuation."""
    timed_tokens: list[tuple[str, float, float]] = []
    for word in words:
        event_tokens = LEXICAL_RE.findall(word.text)
        count = len(event_tokens)
        if count == 0:
            continue
        step = max((word.end - word.start) / count, 0.001)
        timed_tokens.extend(
            (token, word.start + step * index, word.start + step * (index + 1))
            for index, token in enumerate(event_tokens)
        )

    whitespace_tokens = list(re.finditer(r"\S+", source))
    lexical_entries: list[tuple[int, str, bool]] = []
    punctuation_entries: list[tuple[int, str, bool]] = []
    for index, match in enumerate(whitespace_tokens):
        raw = match.group()
        inner = list(LEXICAL_RE.finditer(raw))
        next_start = whitespace_tokens[index + 1].start() if index + 1 < len(whitespace_tokens) else len(source)
        line_break = "\n" in source[match.end() : next_start]
        if not inner:
            if raw not in {"-", "...", "…"}:
                punctuation_entries.append((match.start(), raw, line_break))
            continue
        for inner_index, token_match in enumerate(inner):
            start = 0 if inner_index == 0 else token_match.start()
            end = inner[inner_index + 1].start() if inner_index + 1 < len(inner) else len(raw)
            display = raw[start:end]
            lexical_entries.append(
                (match.start() + token_match.start(), display, line_break and inner_index == len(inner) - 1)
            )

    def normalized(value: str) -> str:
        return value.casefold().replace("’", "'")

    source_values = [normalized(LEXICAL_RE.search(display).group()) for _pos, display, _break in lexical_entries]
    timed_values = [normalized(token) for token, _start, _end in timed_tokens]
    matcher = difflib.SequenceMatcher(a=source_values, b=timed_values, autojunk=False)
    short_sample_tolerance = max(len(source_values), len(timed_values)) <= 20 and abs(len(source_values) - len(timed_values)) <= 2
    if matcher.ratio() < 0.98 and not short_sample_tolerance:
        raise RuntimeError(
            "WordBoundary khác source quá nhiều: "
            f"source={len(source_values)}, timing={len(timed_values)}, ratio={matcher.ratio():.4f}"
        )

    aligned_times: list[tuple[float, float] | None] = [None] * len(source_values)
    inserted = deleted = replaced = 0
    for tag, source_start, source_end, timed_start, timed_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(source_end - source_start):
                _token, start, end = timed_tokens[timed_start + offset]
                aligned_times[source_start + offset] = (start, end)
        elif tag == "replace":
            replaced += max(source_end - source_start, timed_end - timed_start)
            if timed_end > timed_start and source_end > source_start:
                span_start = timed_tokens[timed_start][1]
                span_end = timed_tokens[timed_end - 1][2]
                step = max((span_end - span_start) / (source_end - source_start), 0.001)
                for offset in range(source_end - source_start):
                    aligned_times[source_start + offset] = (
                        span_start + step * offset,
                        span_start + step * (offset + 1),
                    )
        elif tag == "delete":
            deleted += source_end - source_start
        elif tag == "insert":
            inserted += timed_end - timed_start

    index = 0
    while index < len(aligned_times):
        if aligned_times[index] is not None:
            index += 1
            continue
        block_start = index
        while index < len(aligned_times) and aligned_times[index] is None:
            index += 1
        block_end = index
        previous_end = aligned_times[block_start - 1][1] if block_start > 0 and aligned_times[block_start - 1] else 0.0
        next_start = aligned_times[block_end][0] if block_end < len(aligned_times) and aligned_times[block_end] else previous_end + 0.2 * (block_end - block_start)
        step = max((next_start - previous_end) / (block_end - block_start), 0.001)
        for offset in range(block_end - block_start):
            aligned_times[block_start + offset] = (
                previous_end + step * offset,
                previous_end + step * (offset + 1),
            )

    if inserted or deleted or replaced or len(source_values) != len(timed_values):
        print(
            "Alignment adjusted: "
            f"source={len(source_values)}, timing={len(timed_values)}, "
            f"inserted={inserted}, deleted={deleted}, replaced={replaced}, "
            f"ratio={matcher.ratio():.6f}",
            flush=True,
        )

    items: list[tuple[int, Word]] = []
    for (position, display, break_after), timing in zip(lexical_entries, aligned_times):
        if timing is None:
            raise RuntimeError("Không nội suy được timing cho source token.")
        start, end = timing
        items.append((position, Word(display, start, end, break_after)))

    lexical_positions = [position for position, _display, _break in lexical_entries]
    lexical_words = [item for _position, item in items]
    punctuation_groups: dict[int, list[tuple[int, str, bool]]] = {}
    for entry in punctuation_entries:
        position = entry[0]
        insert_at = 0
        while insert_at < len(lexical_positions) and lexical_positions[insert_at] < position:
            insert_at += 1
        punctuation_groups.setdefault(insert_at, []).append(entry)
    for insert_at, group in punctuation_groups.items():
        previous_end = lexical_words[insert_at - 1].end if insert_at > 0 else 0.0
        next_start = lexical_words[insert_at].start if insert_at < len(lexical_words) else previous_end + 0.25
        step = max((next_start - previous_end) / len(group), 0.05)
        for group_index, (position, punctuation, break_after) in enumerate(group):
            start = previous_end + step * group_index
            end = min(next_start, start + step) if next_start > start else start + 0.05
            items.append((position, Word(punctuation, start, end, break_after)))

    return [word for _position, word in sorted(items, key=lambda item: item[0])]


async def render_part_once(text: str, output: Path, voice: str, rate: str, pitch: str) -> list[Word]:
    words: list[Word] = []
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        boundary="WordBoundary",
        connect_timeout=20,
        receive_timeout=90,
    )
    with output.open("wb") as audio:
        async for event in communicate.stream():
            if event["type"] == "audio":
                audio.write(event["data"])
            elif event["type"] == "WordBoundary":
                start = event["offset"] / 10_000_000
                duration = event["duration"] / 10_000_000
                words.append(Word(str(event["text"]), start, start + duration))
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("Edge TTS không trả về dữ liệu âm thanh.")
    return words


async def render_part(text: str, output: Path, voice: str, rate: str, pitch: str) -> list[Word]:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        output.unlink(missing_ok=True)
        try:
            return await asyncio.wait_for(
                render_part_once(text, output, voice, rate, pitch),
                timeout=120,
            )
        except Exception as exc:
            last_error = exc
            if attempt < 4:
                print(f"  retry {attempt}/3: {type(exc).__name__}", flush=True)
                await asyncio.sleep(attempt * 2)
    raise RuntimeError(f"Edge TTS thất bại sau 4 lần thử: {last_error}") from last_error


def probe_duration(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    return float(subprocess.check_output(command, text=True).strip())


def mp3_duration(path: Path) -> float:
    """Read MPEG audio frame durations locally without spawning ffprobe."""
    data = path.read_bytes()
    offset = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = 0
        for value in data[6:10]:
            size = (size << 7) | (value & 0x7F)
        offset = 10 + size
    bitrate_tables = {
        (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
        (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    }
    sample_tables = {1: [44100, 48000, 32000], 2: [22050, 24000, 16000], 25: [11025, 12000, 8000]}
    seconds = 0.0
    frames = 0
    while offset + 4 <= len(data):
        header = int.from_bytes(data[offset:offset + 4], "big")
        if header & 0xFFE00000 != 0xFFE00000:
            offset += 1
            continue
        version_bits = (header >> 19) & 3
        layer_bits = (header >> 17) & 3
        bitrate_index = (header >> 12) & 15
        sample_index = (header >> 10) & 3
        padding = (header >> 9) & 1
        version = {3: 1, 2: 2, 0: 25}.get(version_bits)
        if version is None or layer_bits != 1 or bitrate_index in (0, 15) or sample_index == 3:
            offset += 1
            continue
        table_version = 1 if version == 1 else 2
        bitrate = bitrate_tables[(table_version, 3)][bitrate_index] * 1000
        sample_rate = sample_tables[version][sample_index]
        samples = 1152 if version == 1 else 576
        frame_size = (144 * bitrate // sample_rate + padding) if version == 1 else (72 * bitrate // sample_rate + padding)
        if frame_size <= 4 or offset + frame_size > len(data):
            break
        seconds += samples / sample_rate
        frames += 1
        offset += frame_size
    if not frames:
        raise RuntimeError(f"Không đọc được MPEG frames: {path}")
    return seconds


def concat_audio(parts: list[Path], output: Path) -> None:
    list_file = output.with_suffix(".concat.txt")
    rows = []
    for part in parts:
        escaped = part.resolve().as_posix().replace("'", "'\\''")
        rows.append(f"file '{escaped}'")
    list_file.write_text("\n".join(rows), encoding="utf-8")
    try:
        run([
            "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c:a", "libmp3lame", "-q:a", "2", str(output),
        ])
    finally:
        list_file.unlink(missing_ok=True)


def caption_text(words: list[Word], line_chars: int) -> str:
    text = " ".join(word.text for word in words)
    if len(text) <= line_chars:
        return text
    if len(text) <= line_chars * 2:
        spaces = [match.start() for match in re.finditer(" ", text)]
        if spaces:
            split_at = min(spaces, key=lambda position: abs(position - len(text) / 2))
            return text[:split_at].rstrip() + "\n" + text[split_at + 1 :].lstrip()
    return "\n".join(textwrap.wrap(text, width=line_chars, break_long_words=False, break_on_hyphens=False))


def split_semantic_unit(words: list[Word], max_chars: int, max_seconds: float) -> list[list[Word]]:
    """Split a long sentence at clause boundaries, never at an arbitrary point when avoidable."""
    conjunctions = {
        "and", "but", "because", "while", "when", "which", "who", "that",
        "so", "then", "although", "though", "however", "therefore", "or",
    }
    fallback_break_words = {
        "at", "with", "without", "upon", "into", "through", "from", "during", "after", "before",
    }
    result: list[list[Word]] = []
    cursor = 0
    while cursor < len(words):
        remaining = words[cursor:]
        remaining_text = " ".join(word.text for word in remaining)
        if len(remaining_text) <= max_chars and remaining[-1].end - remaining[0].start <= max_seconds:
            result.append(remaining)
            break

        hard_end = cursor + 1
        preferred: list[int] = []
        all_preferred: list[int] = []
        fallback_preferred: list[int] = []
        for end in range(cursor + 1, len(words) + 1):
            candidate = words[cursor:end]
            chars = len(" ".join(word.text for word in candidate))
            duration = candidate[-1].end - candidate[0].start
            if chars > max_chars or duration > max_seconds:
                break
            hard_end = end
            last = candidate[-1].text
            next_word = words[end].text.casefold().strip("\"'“”‘’()[]") if end < len(words) else ""
            if re.search(r"[,;:][\"'”’)]*$", last) or next_word in conjunctions:
                all_preferred.append(end)
                if chars >= max_chars * 0.45:
                    preferred.append(end)
            elif next_word in fallback_break_words and chars >= max_chars * 0.45:
                fallback_preferred.append(end)

        extended_boundary: int | None = None
        if not all_preferred and not fallback_preferred and hard_end < len(words):
            for end in range(hard_end + 1, len(words) + 1):
                candidate = words[cursor:end]
                chars = len(" ".join(word.text for word in candidate))
                duration = candidate[-1].end - candidate[0].start
                if chars > max_chars + 20 or duration > max_seconds + 1.5:
                    break
                last = candidate[-1].text
                next_word = words[end].text.casefold().strip("\"'“”‘’()[]") if end < len(words) else ""
                if end == len(words) or re.search(r"[,;:][\"'”’)]*$", last) or next_word in conjunctions:
                    extended_boundary = end
                    break

        split_at = (
            all_preferred[-1]
            if all_preferred
            else fallback_preferred[-1]
            if fallback_preferred
            else extended_boundary
            if extended_boundary is not None
            else hard_end
        )
        hard_tail = words[hard_end:]
        tail_chars = len(" ".join(word.text for word in hard_tail))
        tail_duration = hard_tail[-1].end - hard_tail[0].start if hard_tail else 0.0
        if hard_tail and (tail_chars < 40 or tail_duration < 2.0):
            viable = []
            for candidate_end in all_preferred:
                tail = words[candidate_end:]
                if not tail:
                    continue
                chars = len(" ".join(word.text for word in tail))
                duration = tail[-1].end - tail[0].start
                if chars <= max_chars and duration <= max_seconds:
                    viable.append(candidate_end)
            if viable:
                split_at = viable[-1]
            else:
                target = cursor + max(1, (len(words) - cursor) // 2)
                split_at = min(range(cursor + 1, hard_end + 1), key=lambda end: abs(end - target))
        result.append(words[cursor:split_at])
        cursor = split_at
    return result


def words_to_cues(
    words: list[Word],
    max_chars: int = 104,
    max_seconds: float = 7.0,
    line_chars: int = 52,
) -> list[Cue]:
    semantic_units: list[list[Word]] = []
    unit: list[Word] = []
    for word in words:
        unit.append(word)
        sentence_end = bool(re.search(r"[.!?…]+[\"'”’)]*$", word.text))
        if sentence_end or word.break_after:
            semantic_units.append(unit)
            unit = []
    if unit:
        semantic_units.append(unit)

    cues: list[Cue] = []
    for semantic_unit in semantic_units:
        for group in split_semantic_unit(semantic_unit, max_chars=max_chars, max_seconds=max_seconds):
            cues.append(Cue(caption_text(group, line_chars), group[0].start, group[-1].end))
    return merge_incomplete_cues(cues, line_chars)


def merge_incomplete_cues(cues: list[Cue], line_chars: int) -> list[Cue]:
    """Merge only hard-split cue tails that do not end at a meaningful boundary."""
    conjunctions = {
        "and", "but", "because", "while", "when", "which", "who", "that",
        "so", "then", "although", "though", "however", "therefore", "or",
    }
    merged: list[Cue] = []
    index = 0
    while index < len(cues):
        cue = cues[index]
        flat = cue.text.replace("\n", " ")
        while index + 1 < len(cues):
            next_cue = cues[index + 1]
            next_flat = next_cue.text.replace("\n", " ")
            next_tokens = LEXICAL_RE.findall(next_flat.casefold())
            next_first = next_tokens[0] if next_tokens else ""
            has_boundary = bool(
                re.search(r"(?:[,;:.!?…]|[—–-])[\"'”’」)\]]*$", flat)
                or re.search(r"[」\]]$", flat)
                or re.match(r"^(?:Chapter\s+\d+|\[|「)", flat, re.IGNORECASE)
                or next_first in conjunctions
            )
            if has_boundary:
                break
            flat = f"{flat} {next_flat}".strip()
            cue = Cue(
                "\n".join(textwrap.wrap(flat, width=line_chars, break_long_words=False, break_on_hyphens=False)),
                cue.start,
                next_cue.end,
            )
            index += 1
        merged.append(cue)
        index += 1
    return merged


def timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(cues: Iterable[Cue], output: Path, hold_until_next: bool = True) -> None:
    cue_list = list(cues)
    if hold_until_next:
        cue_list = [
            Cue(
                cue.text,
                cue.start,
                max(cue.end, cue_list[index + 1].start) if index + 1 < len(cue_list) else cue.end,
            )
            for index, cue in enumerate(cue_list)
        ]
    blocks = [
        f"{index}\n{timestamp(cue.start)} --> {timestamp(cue.end)}\n{cue.text}"
        for index, cue in enumerate(cue_list, 1)
    ]
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


async def synthesize(
    text: str,
    output: Path,
    voice: str,
    rate: str,
    pitch: str,
    cache_dir: Path | None = None,
    concurrency: int = 6,
    chunk_chars: int = 1400,
    cache_only: bool = False,
) -> list[Word]:
    chunks = split_for_tts(text, max_chars=chunk_chars)
    cache_dir = cache_dir or output.parent / "tts_parts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def create_part(index: int, chunk: str) -> tuple[Path, list[Word]]:
        part = cache_dir / f"part_{index:04}.mp3"
        timing = cache_dir / f"part_{index:04}.json"
        chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        if part.is_file() and part.stat().st_size > 0 and timing.is_file():
            saved = json.loads(timing.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("text_sha256") == chunk_hash:
                print(f"TTS {index}/{len(chunks)} cached", flush=True)
                return part, [Word(**item) for item in saved["words"]]
        if cache_only:
            raise RuntimeError(
                f"--tts-cache-only: thiếu hoặc sai hash cache cho chunk {index}/{len(chunks)}"
            )
        async with semaphore:
            print(f"TTS {index}/{len(chunks)}", flush=True)
            local_words = await render_part(chunk, part, voice, rate, pitch)
            timing.write_text(
                json.dumps({
                    "text_sha256": chunk_hash,
                    "words": [word.__dict__ for word in local_words],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            return part, local_words

    completed = await asyncio.gather(*(
        create_part(index, chunk) for index, chunk in enumerate(chunks, 1)
    ))
    all_words: list[Word] = []
    part_files: list[Path] = []
    cursor = 0.0
    for part, local_words in completed:
        all_words.extend(
            Word(w.text, w.start + cursor, w.end + cursor, w.break_after)
            for w in local_words
        )
        part_files.append(part)
        cursor += mp3_duration(part)
    concat_audio(part_files, output)
    return all_words


def make_video(
    audio: Path,
    srt: Path,
    background: Path | None,
    output: Path,
    text: str = "",
    scene_seconds: float = 12.0,
    video_fps: int = 12,
    words: list[Word] | None = None,
    story_image_dir: Path | None = None,
    visual_layout: str = "quote",
    image_hold_scenes: int = 3,
) -> None:
    duration = probe_duration(audio)
    storyboard_dir = output.parent / "storyboard"
    use_split = visual_layout == "split" and story_image_dir is not None and words is not None
    if use_split:
        scenes = build_source_line_storyboard(
            text, words, duration, target_seconds=scene_seconds, max_chars=560,
        )
        story_images = sorted(
            path for path in story_image_dir.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if not story_images:
            raise RuntimeError(f"Không tìm thấy ảnh truyện trong: {story_image_dir}")
        storyboard_dir.mkdir(parents=True, exist_ok=True)
        images = []
        for index, scene in enumerate(scenes):
            image_path = storyboard_dir / f"scene_{index:05}.jpg"
            selected = story_images[(index // max(1, image_hold_scenes)) % len(story_images)]
            render_image_layout(
                scene, selected, image_path, "split", index,
                progress=scene.start / max(duration, 0.001),
            )
            images.append(image_path)
        valid = {path.name for path in images}
        for stale in storyboard_dir.glob("scene_*.jpg"):
            if stale.name not in valid:
                stale.unlink()
    else:
        scenes = build_cue_storyboard(
            read_srt_cues(srt), duration, target_seconds=scene_seconds,
        )
        images = render_storyboard(scenes, storyboard_dir, background)

    # The concat demuxer advances by each declared image duration. Scene text
    # timing can contain natural TTS pauses between pages, so summing only the
    # spoken spans would make the video stream end before the narration. Keep
    # every scene visible until the next one begins and let the final scene fill
    # the remaining audio duration.
    synchronize_scene_durations(scenes, duration)
    concat = storyboard_dir / "storyboard.ffconcat"
    rows = ["ffconcat version 1.0"]
    for path, scene in zip(images, scenes):
        rows.extend([f"file '{path.resolve().as_posix()}'", f"duration {scene.duration:.3f}"])
    rows.append(f"file '{images[-1].resolve().as_posix()}'")
    concat.write_text("\n".join(rows) + "\n", encoding="utf-8")
    video_filter = (
        f"fps={video_fps},scale=2048:1152:force_original_aspect_ratio=increase,crop=2048:1152,"
        "zoompan=z='min(zoom+0.00025,1.05)':x='iw/2-(iw/zoom/2)+sin(on/35)*8':"
        f"y='ih/2-(ih/zoom/2)+cos(on/41)*6':d=1:s=1920x1080:fps={video_fps},format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(audio), "-i", str(srt), "-map", "0:v:0", "-map", "1:a:0", "-map", "2:0", "-vf", video_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-r", str(video_fps),
        "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-metadata:s:s:0",
        "language=eng", "-t", f"{duration:.3f}", "-pix_fmt", "yuv420p", str(output),
    ])


def synchronize_scene_durations(scenes: list[object], duration: float) -> None:
    """Make concat transitions land on the absolute start of each scene."""
    for index, scene in enumerate(scenes):
        timeline_start = 0.0 if index == 0 else float(scene.start)
        timeline_end = float(scenes[index + 1].start) if index + 1 < len(scenes) else duration
        scene.duration = max(0.08, timeline_end - timeline_start)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def read_srt_cues(path: Path) -> list[Cue]:
    def parse(value: str) -> float:
        hours, minutes, tail = value.split(":")
        seconds, millis = tail.split(",")
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000

    cues: list[Cue] = []
    for block in re.split(r"\r?\n\r?\n+", path.read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ")
        cues.append(Cue("\n".join(lines[2:]), parse(start), parse(end)))
    return cues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Ava narration, millisecond SRT, and MP4 from novel text.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text-file", type=Path, help="UTF-8 TXT file you may use")
    source.add_argument("--url", help="Chapter URL you may access and use")
    parser.add_argument("--confirm-rights", action="store_true", help="Confirm permission/rights for URL content")
    parser.add_argument("--title", help="Override story/chapter title")
    parser.add_argument("--background", type=Path, help="Background JPG/PNG")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default="-5%", help="Edge TTS rate, e.g. -5%%")
    parser.add_argument("--pitch", default="-2Hz", help="Edge TTS pitch, e.g. -2Hz")
    parser.add_argument("--sample-chars", type=int, default=0, help="Only render first N characters; 0 means all")
    parser.add_argument("--cue-max-chars", type=int, default=104, help="Maximum characters per semantic cue")
    parser.add_argument("--cue-max-seconds", type=float, default=7.0, help="Maximum spoken seconds per cue")
    parser.add_argument("--subtitle-line-chars", type=int, default=52, help="Wrap subtitles near this line width")
    parser.add_argument("--scene-seconds", type=float, default=12.0, help="Seconds per dynamic story visual (6-30)")
    parser.add_argument("--video-fps", type=int, default=12, choices=(8, 12, 24), help="Storyboard motion FPS")
    parser.add_argument("--tts-concurrency", type=int, default=6, help="Parallel Edge TTS requests (1-10)")
    parser.add_argument("--tts-chunk-chars", type=int, default=1400, help="Characters per parallel TTS part (800-1800)")
    parser.add_argument("--tts-cache-only", action="store_true", help="Use verified TTS cache only; never call Edge TTS")
    parser.add_argument("--visual-layout", choices=("quote", "split"), default="quote")
    parser.add_argument("--story-image-dir", type=Path, help="Folder of story images for split layout")
    parser.add_argument("--image-hold-scenes", type=int, default=3, help="Keep each image for N scenes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("Cần cài ffmpeg và ffprobe trong PATH.")

    if args.url:
        if not args.confirm_rights:
            raise SystemExit("URL yêu cầu --confirm-rights để xác nhận bạn có quyền sử dụng nội dung.")
        page_title, text = fetch_url(args.url)
        title = args.title or page_title
    else:
        path = args.text_file.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"Không tìm thấy TXT: {path}")
        text = normalize_text(path.read_text(encoding="utf-8-sig"))
        title = args.title or path.stem

    if args.sample_chars > 0:
        text = text[: args.sample_chars].rsplit(" ", 1)[0].rstrip() + "…"
    if not text.strip():
        raise SystemExit("Nội dung rỗng.")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_txt = output_dir / "source.txt"
    audio = output_dir / "narration_ava.mp3"
    srt = output_dir / "subtitles.en.srt"
    video = output_dir / "video.mp4"
    source_txt.write_text(text, encoding="utf-8")

    if not 1 <= args.tts_concurrency <= 10:
        raise SystemExit("--tts-concurrency phải nằm trong khoảng 1 đến 10.")
    if not 800 <= args.tts_chunk_chars <= 1800:
        raise SystemExit("--tts-chunk-chars phải nằm trong khoảng 800 đến 1800.")
    words = asyncio.run(synthesize(
        text, audio, args.voice, args.rate, args.pitch,
        cache_dir=output_dir / "tts_parts", concurrency=args.tts_concurrency,
        chunk_chars=args.tts_chunk_chars, cache_only=args.tts_cache_only,
    ))
    if not words:
        raise SystemExit("TTS không trả về mốc thời gian từ nào.")
    raw_word_timings = output_dir / "raw_word_timings.json"
    raw_word_timings.write_text(
        json.dumps([word.__dict__ for word in words], ensure_ascii=False),
        encoding="utf-8",
    )
    words = align_words_to_source(words, text)
    word_timings = output_dir / "word_timings.json"
    word_timings.write_text(
        json.dumps([word.__dict__ for word in words], ensure_ascii=False),
        encoding="utf-8",
    )
    write_srt(
        words_to_cues(
            words,
            max_chars=args.cue_max_chars,
            max_seconds=args.cue_max_seconds,
            line_chars=args.subtitle_line_chars,
        ),
        srt,
    )
    background = args.background.expanduser().resolve() if args.background else None
    if background and not background.is_file():
        raise SystemExit(f"Không tìm thấy ảnh nền: {background}")
    story_image_dir = args.story_image_dir.expanduser().resolve() if args.story_image_dir else None
    if args.visual_layout == "split" and (story_image_dir is None or not story_image_dir.is_dir()):
        raise SystemExit("--visual-layout split yêu cầu --story-image-dir hợp lệ.")
    if args.image_hold_scenes < 1:
        raise SystemExit("--image-hold-scenes phải lớn hơn hoặc bằng 1.")
    if not 6 <= args.scene_seconds <= 30:
        raise SystemExit("--scene-seconds phải nằm trong khoảng 6 đến 30.")
    make_video(
        audio, srt, background, video, text=text,
        scene_seconds=args.scene_seconds, video_fps=args.video_fps,
        words=words, story_image_dir=story_image_dir,
        visual_layout=args.visual_layout, image_hold_scenes=args.image_hold_scenes,
    )

    metadata = {
        "title": title,
        "source_url": args.url,
        "voice": args.voice,
        "rate": args.rate,
        "pitch": args.pitch,
        "duration_seconds": round(probe_duration(audio), 3),
        "visuals": {
            "mode": "storyboard",
            "scene_seconds": args.scene_seconds,
            "video_fps": args.video_fps,
            "layout": args.visual_layout,
            "story_image_dir": str(story_image_dir) if story_image_dir else None,
            "image_hold_scenes": args.image_hold_scenes,
        },
        "subtitle": {
            "cue_max_chars": args.cue_max_chars,
            "cue_max_seconds": args.cue_max_seconds,
            "line_chars": args.subtitle_line_chars,
        },
        "files": {
            "text": source_txt.name,
            "audio": audio.name,
            "srt": srt.name,
            "word_timings": word_timings.name,
            "raw_word_timings": raw_word_timings.name,
            "video": video.name,
        },
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done: {output_dir}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        raise SystemExit(f"Không tải được URL: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"FFmpeg thất bại (exit {exc.returncode}).") from exc
