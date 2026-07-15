from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from image_layouts import render_image_layout
from novel_video import Word, probe_duration, read_srt_cues, write_srt
from story_visuals import build_source_line_storyboard


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a short showcase of image/text scene layouts.")
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=150.0)
    parser.add_argument("--scene-seconds", type=float, default=18.0)
    parser.add_argument("--layout", choices=("rotate", "cinematic", "split", "hero_banner"), default="rotate")
    parser.add_argument("--image-hold-scenes", type=int, default=1)
    args = parser.parse_args()

    source_dir = args.source_output.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(path for path in args.image_dir.resolve().iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not images:
        raise SystemExit("Không tìm thấy ảnh truyện.")

    audio = output_dir / "audio.mp3"
    srt = output_dir / "subtitles.srt"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(source_dir / "narration_ava.mp3"),
         "-t", str(args.duration), "-c:a", "libmp3lame", "-q:a", "2", str(audio)])
    cues = [cue for cue in read_srt_cues(source_dir / "subtitles.en.srt") if cue.start < args.duration]
    write_srt(cues, srt)
    saved_words = json.loads((source_dir / "word_timings.json").read_text(encoding="utf-8"))
    words = [Word(**item) for item in saved_words]
    source = (source_dir / "source.txt").read_text(encoding="utf-8")
    scenes = [
        scene for scene in build_source_line_storyboard(
            source, words, args.duration,
            target_seconds=args.scene_seconds, max_chars=560,
        ) if scene.start < args.duration
    ]

    layouts = ("cinematic", "split", "hero_banner") if args.layout == "rotate" else (args.layout,)
    storyboard = output_dir / "storyboard"
    paths: list[Path] = []
    rows = ["ffconcat version 1.0"]
    for index, scene in enumerate(scenes):
        layout = layouts[index % len(layouts)]
        path = storyboard / f"{index+1:02}_{layout}.jpg"
        image_index = (index // max(1, args.image_hold_scenes)) % len(images)
        render_image_layout(
            scene, images[image_index], path, layout, index,
            progress=scene.start / max(args.duration, 0.001),
        )
        paths.append(path)
        rows.extend([f"file '{path.resolve().as_posix()}'", f"duration {scene.duration:.3f}"])
    rows.append(f"file '{paths[-1].resolve().as_posix()}'")
    concat = storyboard / "showcase.ffconcat"
    concat.write_text("\n".join(rows) + "\n", encoding="utf-8")

    output = output_dir / "layout_showcase.mp4"
    video_filter = (
        "fps=8,scale=2048:1152:force_original_aspect_ratio=increase,crop=2048:1152,"
        "zoompan=z='min(zoom+0.00022,1.035)':x='iw/2-(iw/zoom/2)+sin(on/43)*6':"
        "y='ih/2-(ih/zoom/2)+cos(on/47)*5':d=1:s=1920x1080:fps=8,format=yuv420p"
    )
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-i", str(audio), "-i", str(srt), "-map", "0:v:0", "-map", "1:a:0", "-map", "2:0",
         "-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-r", "8",
         "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
         "-t", f"{min(args.duration, probe_duration(audio)):.3f}", "-pix_fmt", "yuv420p", str(output)])
    print(f"Done: {output}")


if __name__ == "__main__":
    main()
