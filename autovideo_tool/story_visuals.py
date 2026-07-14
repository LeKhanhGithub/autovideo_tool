from __future__ import annotations

import hashlib
import math
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for",
    "with", "from", "by", "as", "is", "was", "were", "be", "been", "it", "its",
    "this", "that", "he", "she", "they", "his", "her", "their", "i", "you", "we",
    "had", "has", "have", "not", "so", "then", "into", "out", "up", "down",
}


@dataclass
class StoryScene:
    start: float
    duration: float
    heading: str
    excerpt: str
    keywords: list[str]
    style: str
    lines: list[str] = field(default_factory=list)
    active_index: int = 0


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def _sentences(text: str) -> list[str]:
    values = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [re.sub(r"\s+", " ", value).strip() for value in values if len(value.strip()) >= 12]


def _keywords(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ỹ][\wÀ-ỹ'-]{2,}", text, re.UNICODE)
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for word in words:
        key = word.casefold()
        if key in STOPWORDS:
            continue
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, word)
    ranked = sorted(counts, key=lambda key: (-counts[key], words.index(display[key])))
    return [display[key] for key in ranked[:limit]] or ["Story", "Journey"]


def build_storyboard(text: str, duration: float, scene_seconds: float = 12.0) -> list[StoryScene]:
    sentences = _sentences(text) or [text.strip() or "Story"]
    count = max(1, math.ceil(duration / scene_seconds))
    scenes: list[StoryScene] = []
    for index in range(count):
        start = index * scene_seconds
        source_position = min(len(sentences) - 1, int(index * len(sentences) / count))
        block = sentences[source_position : source_position + 3]
        excerpt = " ".join(block)
        if len(excerpt) > 310:
            excerpt = excerpt[:307].rsplit(" ", 1)[0] + "…"
        chapter = next((s for s in block if re.match(r"chapter\s+\d+", s, re.I)), "")
        heading = chapter[:70] if chapter else f"Story moment {index + 1}"
        scenes.append(StoryScene(
            start=start,
            duration=min(scene_seconds, max(0.1, duration - start)),
            heading=heading,
            excerpt=excerpt,
            keywords=_keywords(" ".join(block)),
            style="story",
            lines=[excerpt],
        ))
    return scenes


def build_cue_storyboard(
    cues: list[object],
    duration: float,
    target_seconds: float = 18.0,
    max_chars: int = 650,
) -> list[StoryScene]:
    """Group consecutive spoken cues into text-first quote cards."""
    if not cues:
        return build_storyboard("Story", duration)
    scenes: list[StoryScene] = []
    index = 0
    while index < len(cues):
        page_start = index
        start = float(getattr(cues[index], "start"))
        page: list[object] = []
        chars = 0
        while index < len(cues):
            candidate = str(getattr(cues[index], "text")).replace("\n", " ")
            candidate_end = float(getattr(cues[index], "end"))
            if page and (chars + len(candidate) > max_chars or candidate_end - start > target_seconds):
                break
            page.append(cues[index])
            chars += len(candidate) + 1
            index += 1
        lines = [str(getattr(item, "text")).replace("\n", " ") for item in page]
        excerpt = " ".join(lines)
        end = float(getattr(page[-1], "end"))
        chapter = re.search(r"Chapter\s+\d+[^.!?]*(?:[.!?]+|$)", excerpt, re.IGNORECASE)
        heading = chapter.group(0).strip() if chapter else f"Story moment {len(scenes) + 1}"
        scenes.append(StoryScene(
            start=start,
            duration=max(0.08, min(duration, end) - start),
            heading=heading,
            excerpt=excerpt,
            keywords=_keywords(" ".join(lines)),
            style="quote_card",
            lines=lines,
        ))
    return scenes


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _base_canvas(background: Path | None, seed: int) -> Image.Image:
    if background:
        image = Image.open(background).convert("RGB")
        ratio = max(1920 / image.width, 1080 / image.height)
        image = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
        left, top = (image.width - 1920) // 2, (image.height - 1080) // 2
        image = image.crop((left, top, left + 1920, top + 1080)).filter(ImageFilter.GaussianBlur(3))
        image = ImageEnhance.Brightness(image).enhance(0.32)
    else:
        palettes = [(9, 20, 38), (28, 16, 42), (8, 35, 41), (42, 24, 15)]
        image = Image.new("RGB", (1920, 1080), palettes[seed % len(palettes)])
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    accent = [(54, 211, 153), (96, 165, 250), (244, 114, 182), (251, 191, 36)][seed % 4]
    for n in range(8):
        x = (seed * 173 + n * 347) % 2100 - 90
        y = (seed * 97 + n * 211) % 1260 - 90
        radius = 80 + (seed + n * 31) % 180
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(*accent, 12 + n * 2))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def render_scene(scene: StoryScene, output: Path, background: Path | None = None, index: int = 0) -> None:
    seed = int(hashlib.sha1(scene.excerpt.encode("utf-8")).hexdigest()[:8], 16)
    image = _base_canvas(background, seed)
    draw = ImageDraw.Draw(image)
    white, muted = (245, 247, 255, 255), (191, 200, 218, 255)
    accent = [(54, 211, 153, 255), (96, 165, 250, 255), (244, 114, 182, 255), (251, 191, 36, 255)][index % 4]
    draw.rounded_rectangle((105, 80, 1815, 1000), radius=42, fill=(5, 10, 22, 178), outline=(*accent[:3], 120), width=3)
    draw.text((160, 130), scene.heading.upper(), font=_font(34, True), fill=accent)

    # Small theme icon: deliberately simple so the story text remains dominant.
    icon_x, icon_y = 1690, 235
    icon_kind = seed % 4
    if icon_kind == 0:  # book
        draw.rounded_rectangle((icon_x-72, icon_y-48, icon_x+72, icon_y+48), 12, outline=accent, width=5)
        draw.line((icon_x, icon_y-45, icon_x, icon_y+45), fill=accent, width=4)
    elif icon_kind == 1:  # sparkle
        draw.polygon([(icon_x, icon_y-70), (icon_x+18, icon_y-18), (icon_x+70, icon_y),
                      (icon_x+18, icon_y+18), (icon_x, icon_y+70), (icon_x-18, icon_y+18),
                      (icon_x-70, icon_y), (icon_x-18, icon_y-18)], outline=accent, fill=(*accent[:3], 45))
    elif icon_kind == 2:  # crossed blades
        draw.line((icon_x-55, icon_y-55, icon_x+55, icon_y+55), fill=accent, width=9)
        draw.line((icon_x+55, icon_y-55, icon_x-55, icon_y+55), fill=accent, width=9)
        draw.ellipse((icon_x-13, icon_y-13, icon_x+13, icon_y+13), fill=accent)
    else:  # energy rings
        for radius in (24, 46, 68):
            draw.ellipse((icon_x-radius, icon_y-radius, icon_x+radius, icon_y+radius), outline=(*accent[:3], 220-radius), width=4)

    keyword = scene.keywords[0][:18] if scene.keywords else "STORY"
    draw.text((icon_x, 330), keyword.upper(), font=_font(21, True), fill=accent, anchor="mm")

    # Large centered quote, with font size adapted to the amount of story text.
    length = len(scene.excerpt)
    font_size = 52 if length <= 240 else 44 if length <= 400 else 37
    quote_font = _font(font_size, True)
    wrapped = _wrap(draw, scene.excerpt, quote_font, 1450)
    line_height = font_size + 16
    max_lines = 11 if font_size <= 37 else 9
    wrapped = wrapped[:max_lines]
    total_height = len(wrapped) * line_height
    y = max(290, 565 - total_height // 2)
    for value in wrapped:
        draw.text((960, y), value, font=quote_font, fill=white, anchor="ma", align="center")
        y += line_height
    draw.rectangle((160, 955, 1760, 960), fill=(60, 75, 100, 180))
    progress = min(1.0, (index + 1) / max(index + 1, 50))
    draw.rectangle((160, 955, 160 + int(1600 * progress), 960), fill=accent)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, quality=94)


def render_storyboard(scenes: list[StoryScene], directory: Path, background: Path | None = None) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, scene in enumerate(scenes):
        path = directory / f"scene_{index:05}.jpg"
        render_scene(scene, path, background, index)
        paths.append(path)
    valid = {path.name for path in paths}
    for stale in directory.glob("scene_*.jpg"):
        if stale.name not in valid:
            stale.unlink()
    return paths
