from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+(?:['’]\w+)*", text.casefold())


def subtitle_text(path: Path) -> str:
    blocks = re.split(r"\r?\n\r?\n+", path.read_text(encoding="utf-8").strip())
    text: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3 and " --> " in lines[1]:
            text.extend(lines[2:])
    return " ".join(text)


def seconds(timestamp: str) -> float:
    hours, minutes, rest = timestamp.split(":")
    secs, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000


def cue_audit(path: Path) -> dict[str, object]:
    blocks = re.split(r"\r?\n\r?\n+", path.read_text(encoding="utf-8").strip())
    cues: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ")
        cues.append((seconds(start), seconds(end), "\n".join(lines[2:])))

    conjunctions = {
        "and", "but", "because", "while", "when", "which", "who", "that",
        "so", "then", "although", "though", "however", "therefore", "or",
    }
    questionable: list[dict[str, object]] = []
    overlaps = invalid = gaps = 0
    previous_end = -1.0
    max_chars = max_duration = max_line_chars = max_lines = 0
    for index, (start, end, text) in enumerate(cues):
        if start < previous_end:
            overlaps += 1
        if previous_end >= 0 and start > previous_end:
            gaps += 1
        if end <= start:
            invalid += 1
        previous_end = end
        flat = text.replace("\n", " ")
        max_chars = max(max_chars, len(flat))
        max_duration = max(max_duration, end - start)
        lines = text.splitlines()
        max_lines = max(max_lines, len(lines))
        max_line_chars = max(max_line_chars, *(len(line) for line in lines))

        if index + 1 < len(cues):
            next_flat = cues[index + 1][2].replace("\n", " ")
            first_next = tokens(next_flat)[0] if tokens(next_flat) else ""
            has_boundary = bool(
                re.search(r"(?:[,;:.!?…]|[—–-])[\"'”’」)\]]*$", flat)
                or re.search(r"[」\]]$", flat)
            )
            is_heading = bool(re.match(r"^(?:chapter\s+\d+|\[|「)", flat, re.IGNORECASE))
            if not has_boundary and not is_heading and first_next not in conjunctions:
                if len(questionable) < 20:
                    questionable.append({"cue": index + 1, "text": flat, "next": next_flat})

    return {
        "cues": len(cues),
        "overlaps": overlaps,
        "invalid_durations": invalid,
        "gaps_between_cues": gaps,
        "max_chars": max_chars,
        "max_duration_seconds": round(max_duration, 3),
        "max_lines": max_lines,
        "max_line_chars": max_line_chars,
        "questionable_boundary_count_shown": len(questionable),
        "questionable_boundary_samples": questionable,
        "first_cue": cues[0][2] if cues else "",
        "last_cue": cues[-1][2] if cues else "",
        "last_end_seconds": cues[-1][1] if cues else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare source tokens with generated SRT text.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--srt", type=Path, required=True)
    args = parser.parse_args()

    source = tokens(args.source.read_text(encoding="utf-8"))
    subtitle = tokens(subtitle_text(args.srt))
    matcher = difflib.SequenceMatcher(None, source, subtitle, autojunk=False)
    counts = {"equal": 0, "delete": 0, "insert": 0, "replace_source": 0, "replace_srt": 0}
    samples: list[dict[str, object]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            counts["equal"] += i2 - i1
        elif tag == "delete":
            counts["delete"] += i2 - i1
        elif tag == "insert":
            counts["insert"] += j2 - j1
        else:
            counts["replace_source"] += i2 - i1
            counts["replace_srt"] += j2 - j1
        if tag != "equal" and len(samples) < 20:
            samples.append({"tag": tag, "source": source[i1:i2], "srt": subtitle[j1:j2]})

    print(json.dumps({
        "source_tokens": len(source),
        "srt_tokens": len(subtitle),
        "match_ratio": round(matcher.ratio(), 6),
        "counts": counts,
        "samples": samples,
        "cue_audit": cue_audit(args.srt),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
