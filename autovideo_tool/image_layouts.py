from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from story_visuals import StoryScene, _font, _wrap


ACCENTS = [(54, 211, 153, 255), (96, 165, 250, 255), (244, 114, 182, 255)]


def _cover(source: Image.Image, size: tuple[int, int], focus_x: float = 0.5) -> Image.Image:
    ratio = max(size[0] / source.width, size[1] / source.height)
    resized = source.resize((round(source.width * ratio), round(source.height * ratio)), Image.Resampling.LANCZOS)
    left = int((resized.width - size[0]) * focus_x)
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def _contain_crop(source: Image.Image, box: tuple[int, int, int, int], focus_x: float = 0.5) -> Image.Image:
    width, height = box[2] - box[0], box[3] - box[1]
    return _cover(source, (width, height), focus_x)


def _icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], accent: tuple[int, int, int, int], kind: int) -> None:
    x, y = center
    if kind == 0:
        draw.rounded_rectangle((x-55, y-38, x+55, y+38), 10, outline=accent, width=5)
        draw.line((x, y-36, x, y+36), fill=accent, width=4)
    elif kind == 1:
        draw.polygon([(x, y-58), (x+15, y-15), (x+58, y), (x+15, y+15),
                      (x, y+58), (x-15, y+15), (x-58, y), (x-15, y-15)],
                     fill=(*accent[:3], 65), outline=accent)
    else:
        for radius in (20, 38, 56):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=accent, width=4)


def _quote(
    draw: ImageDraw.ImageDraw,
    scene: StoryScene,
    box: tuple[int, int, int, int],
    color=(248, 250, 255, 255),
    stroke_width: int = 0,
) -> None:
    width = box[2] - box[0]
    length = len(scene.excerpt)
    size = 47 if length <= 260 else 40 if length <= 430 else 34
    font = _font(size, True)
    lines = _wrap(draw, scene.excerpt, font, width - 100)
    line_height = size + 14
    total = len(lines) * line_height
    y = box[1] + max(18, ((box[3] - box[1]) - total) // 2)
    for line in lines[:11]:
        draw.text(
            ((box[0] + box[2]) // 2, y), line, font=font, fill=color,
            anchor="ma", align="center", stroke_width=stroke_width,
            stroke_fill=(0, 3, 12, 235),
        )
        y += line_height


def _paragraph_quote(
    draw: ImageDraw.ImageDraw,
    scene: StoryScene,
    box: tuple[int, int, int, int],
    accent: tuple[int, int, int, int],
) -> None:
    """Render cue boundaries as readable paragraphs, preserving story rhythm."""
    paragraphs = [value.strip() for value in scene.lines if value.strip()] or [scene.excerpt]
    available_width = box[2] - box[0] - 40
    available_height = box[3] - box[1] - 40
    chosen: tuple[object, list[list[str]], int, int] | None = None
    for size in (43, 40, 37, 34, 31):
        font = _font(size, True)
        wrapped = [_wrap(draw, paragraph, font, available_width) for paragraph in paragraphs]
        line_height = size + 13
        paragraph_gap = 18
        total = sum(len(lines) * line_height for lines in wrapped) + max(0, len(wrapped) - 1) * paragraph_gap
        chosen = (font, wrapped, line_height, paragraph_gap)
        if total <= available_height:
            break
    assert chosen is not None
    font, wrapped, line_height, paragraph_gap = chosen
    total = sum(len(lines) * line_height for lines in wrapped) + max(0, len(wrapped) - 1) * paragraph_gap
    y = box[1] + max(20, (box[3] - box[1] - total) // 2)
    text_x = box[0] + 20
    for paragraph_index, lines in enumerate(wrapped):
        for line_index, line in enumerate(lines):
            color = (249, 250, 255, 255) if paragraph_index == 0 else (224, 231, 242, 255)
            draw.text(
                (text_x, y), line, font=font, fill=color,
                stroke_width=2, stroke_fill=(0, 3, 12, 235),
            )
            y += line_height
        if paragraph_index + 1 < len(wrapped):
            y += paragraph_gap


def render_image_layout(
    scene: StoryScene,
    story_image: Path,
    output: Path,
    layout: str,
    index: int,
    progress: float = 0.0,
) -> None:
    source = Image.open(story_image).convert("RGB")
    seed = int(hashlib.sha1((scene.excerpt + layout).encode("utf-8")).hexdigest()[:8], 16)
    accent = ACCENTS[index % len(ACCENTS)]

    if layout == "cinematic":
        canvas = _cover(source, (1920, 1080), 0.5).filter(ImageFilter.GaussianBlur(12))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.35).convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle((105, 75, 1815, 1005), 42, fill=(4, 9, 20, 190), outline=accent, width=3)
        draw.text((155, 125), "CINEMATIC BACKGROUND", font=_font(23, True), fill=accent)
        draw.text((155, 175), scene.heading.upper(), font=_font(32, True), fill=(245, 248, 255, 255))
        _icon(draw, (1690, 165), accent, seed % 3)
        _quote(draw, scene, (210, 265, 1710, 890))
        canvas = Image.alpha_composite(canvas, overlay)

    elif layout == "split":
        canvas = Image.new("RGBA", (1920, 1080), (5, 11, 24, 255))
        image_box = (0, 0, 790, 1080)
        portrait = _contain_crop(source, image_box, 0.58).convert("RGBA")
        canvas.paste(portrait, image_box[:2])
        gradient = Image.new("RGBA", (520, 1080), (0, 0, 0, 0))
        pixels = gradient.load()
        for x in range(520):
            alpha = int(255 * (x / 519) ** 1.7)
            for y in range(1080):
                pixels[x, y] = (5, 11, 24, alpha)
        canvas.alpha_composite(gradient, (430, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((785, 0, 795, 1080), fill=accent)
        draw.rectangle((807, 28, 1892, 1052), outline=(*accent[:3], 145), width=3)
        # Decorative corner brackets and small constellation dots.
        draw.line((835, 65, 945, 65), fill=accent, width=5)
        draw.line((835, 65, 835, 135), fill=accent, width=5)
        draw.line((1862, 945, 1862, 1015), fill=accent, width=5)
        draw.line((1752, 1015, 1862, 1015), fill=accent, width=5)
        for dot, radius in [((1815, 255), 6), ((1765, 285), 4), ((1845, 320), 3)]:
            draw.ellipse((dot[0]-radius, dot[1]-radius, dot[0]+radius, dot[1]+radius), fill=accent)
        draw.rounded_rectangle((865, 78, 1075, 122), 20, fill=accent, outline=(245, 248, 255, 180), width=2)
        draw.text((970, 100), f"SCENE {index + 1:02}", font=_font(20, True), fill=(5, 11, 24, 255), anchor="mm")
        draw.text((875, 155), scene.heading.upper(), font=_font(31, True), fill=(245, 248, 255, 255))
        _icon(draw, (1730, 150), accent, seed % 3)
        draw.rounded_rectangle((845, 250, 1835, 905), 30, fill=(9, 18, 36, 95), outline=(*accent[:3], 105), width=2)
        text_color = tuple(min(255, int(235 + channel * 0.08)) for channel in accent[:3]) + (255,)
        _paragraph_quote(draw, scene, (875, 275, 1805, 875), accent)
        # Timeline: track, elapsed segment, glowing current marker.
        bar_left, bar_right, bar_y = 855, 1845, 980
        draw.rounded_rectangle((bar_left, bar_y, bar_right, bar_y + 9), 5, fill=(54, 67, 91, 255))
        elapsed_x = bar_left + int((bar_right - bar_left) * max(0.0, min(1.0, progress)))
        draw.rounded_rectangle((bar_left, bar_y, max(bar_left + 8, elapsed_x), bar_y + 9), 5, fill=accent)
        draw.ellipse((elapsed_x-10, bar_y-6, elapsed_x+10, bar_y+15), fill=(*accent[:3], 55))
        draw.ellipse((elapsed_x-5, bar_y-1, elapsed_x+5, bar_y+10), fill=accent)

    else:  # hero_banner
        canvas = Image.new("RGBA", (1920, 1080), (5, 11, 24, 255))
        hero = _cover(source, (1920, 470), 0.5).convert("RGBA")
        hero = ImageEnhance.Brightness(hero).enhance(0.72)
        canvas.paste(hero, (0, 0))
        shade = Image.new("RGBA", (1920, 250), (0, 0, 0, 0))
        shade_pixels = shade.load()
        for y in range(250):
            alpha = int(255 * (y / 249))
            for x in range(1920):
                shade_pixels[x, y] = (5, 11, 24, alpha)
        canvas.alpha_composite(shade, (0, 220))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 462, 1920, 470), fill=accent)
        draw.text((135, 515), "HERO BANNER", font=_font(23, True), fill=accent)
        draw.text((135, 565), scene.heading.upper(), font=_font(31, True), fill=(245, 248, 255, 255))
        _icon(draw, (1730, 555), accent, seed % 3)
        _quote(draw, scene, (145, 640, 1775, 1010))

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, quality=94)
