from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_video import Word, align_words_to_source, make_video, words_to_cues, write_srt


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild semantic SRT/MP4 from saved Ava word timings.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--background", type=Path, required=True)
    parser.add_argument("--cue-max-chars", type=int, default=104)
    parser.add_argument("--cue-max-seconds", type=float, default=7.0)
    parser.add_argument("--subtitle-line-chars", type=int, default=52)
    parser.add_argument("--scene-seconds", type=float, default=12.0)
    parser.add_argument("--video-fps", type=int, default=12, choices=(8, 12, 24))
    parser.add_argument("--visual-layout", choices=("quote", "split"), default="quote")
    parser.add_argument("--story-image-dir", type=Path)
    parser.add_argument("--image-hold-scenes", type=int, default=3)
    parser.add_argument("--skip-video", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    source_path = output_dir / "source.txt"
    timings_path = output_dir / "word_timings.json"
    audio_path = output_dir / "narration_ava.mp3"
    srt_path = output_dir / "subtitles.en.srt"
    video_path = output_dir / "video.mp4"
    background = args.background.expanduser().resolve()
    story_image_dir = args.story_image_dir.expanduser().resolve() if args.story_image_dir else None

    for path in (source_path, timings_path, audio_path, background):
        if not path.is_file():
            raise SystemExit(f"Không tìm thấy: {path}")

    source = source_path.read_text(encoding="utf-8")
    saved = json.loads(timings_path.read_text(encoding="utf-8"))
    words = align_words_to_source([Word(**item) for item in saved], source)
    timings_path.write_text(
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
        srt_path,
    )

    if not args.skip_video:
        temporary_video = output_dir / "video.recaptioning.mp4"
        make_video(
            audio_path, srt_path, background, temporary_video,
            text=source, scene_seconds=args.scene_seconds, video_fps=args.video_fps,
            words=words, story_image_dir=story_image_dir,
            visual_layout=args.visual_layout, image_hold_scenes=args.image_hold_scenes,
        )
        temporary_video.replace(video_path)
    print(f"Done: {srt_path}")


if __name__ == "__main__":
    main()
