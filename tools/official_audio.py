"""Attach audio segments to official listening questions.

Usage: python tools/official_audio.py [--dry-run]

Input: content/official/audio_segments/<set>_N2Q<mondai>.json, made by a speech-to-text pass (faster-whisper)
over raw/<set>/N2Q<mondai>.mp3: {"duration": seconds, "segments": [{"start", "end", "text"}, ...]}.

Alignment uses the official transcript of every item (its "script"): the opening line of each item is
fuzzy-matched against the recognized segments, and a dynamic program picks the best strictly increasing
assignment (a segment that also starts with the right 「N番」 gets a bonus). Recognition slips therefore do
not matter. An item runs from its start (including a separate 「N番」 announcement just before it) to 1.5 s
after its last speech before the next item, which trims the silent answer pause. Items sharing a number
(問題5 「3番 質問1/質問2」) share one clip. Weak matches are reported and the file is left untouched.
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from n2.bank import strip_markup  # noqa: E402

OFFICIAL_DIR = Path(__file__).resolve().parent.parent / "content" / "official"
KANJI_DIGITS = str.maketrans("一二三四五六七八九０１２３４５６７８９", "1234567890123456789")
MARKER = re.compile(r"^\s*([0-9０-９一二三四五六七八九十]+)\s*番(?!目)")
SPEAKER = re.compile(r"^[^：:\n]{1,12}[：:]")
LEAD_IN = 0.3
MISSED_ANNOUNCEMENT_LEAD_IN = 3.5
TAIL = 1.5
MIN_SCORE = 0.45
OPENING_LENGTH = 24


def item_number(question: dict) -> int:
    match = re.search(r"([0-9０-９]+)\s*番", strip_markup(question["question"]))
    if not match:
        raise ValueError(f"{question['id']}: question label {question['question']!r} has no item number")
    return int(match.group(1).translate(KANJI_DIGITS))


def marker_number(text: str) -> int | None:
    match = MARKER.match(text)
    if not match:
        return None
    digits = match.group(1).translate(KANJI_DIGITS).replace("十", "1" if len(match.group(1)) == 1 else "")
    return int(digits) if digits.isdigit() else None


def normalize(text: str) -> str:
    return re.sub(r"[\s、。，．・「」『』（）()？！?!…ー\-]", "", text)


def opening(question: dict) -> str:
    lines = [SPEAKER.sub("", line).strip() for line in strip_markup(question["script"]).splitlines()]
    text = "".join(line for line in lines if line)
    text = MARKER.sub("", text)
    return normalize(text)[:OPENING_LENGTH]


def score(segments: list[dict], index: int, target: str, number: int) -> float:
    text = segments[index]["text"]
    following = segments[index + 1]["text"] if index + 1 < len(segments) else ""
    body = normalize(MARKER.sub("", text) + following)[: len(target) + 6]
    similarity = SequenceMatcher(None, body, target).ratio()
    if not normalize(MARKER.sub("", text)) and following:  # a bare 「N番」 segment: judge it by the next one
        similarity = SequenceMatcher(None, normalize(following)[: len(target) + 6], target).ratio()
    return similarity + (0.3 if marker_number(text) == number else 0.0)


def align(segments: list[dict], targets: list[tuple[int, str]]) -> tuple[list[int], list[float]]:
    """Best strictly increasing segment index per target (dynamic programming over targets x segments)."""
    count = len(segments)
    best: list[list[float]] = []
    back: list[list[int]] = []
    for position, (number, target) in enumerate(targets):
        scores = [score(segments, index, target, number) for index in range(count)]
        row, links = [float("-inf")] * count, [-1] * count
        running, running_index = float("-inf"), -1
        for index in range(count):
            if position == 0:
                row[index] = scores[index]
                continue
            if index > 0 and best[-1][index - 1] > running:
                running, running_index = best[-1][index - 1], index - 1
            if running_index >= 0:
                row[index], links[index] = running + scores[index], running_index
        best.append(row)
        back.append(links)
    index = max(range(count), key=lambda candidate: best[-1][candidate])
    chosen = [index]
    for position in range(len(targets) - 1, 0, -1):
        index = back[position][index]
        chosen.append(index)
    chosen.reverse()
    item_scores = [score(segments, index, target, number) for index, (number, target) in zip(chosen, targets)]
    return chosen, item_scores


def clip_bounds(segments: list[dict], starts: list[int], duration: float) -> list[tuple[float, float]]:
    bounds = []
    for position, index in enumerate(starts):
        first = index - 1 if index > 0 and marker_number(segments[index - 1]["text"]) and not normalize(
            MARKER.sub("", segments[index - 1]["text"])) else index
        following = starts[position + 1] if position + 1 < len(starts) else len(segments)
        next_start = segments[following]["start"] - LEAD_IN if following < len(segments) else duration
        if following < len(segments) and following - 1 > index and marker_number(segments[following - 1]["text"]) \
                and not normalize(MARKER.sub("", segments[following - 1]["text"])):
            following -= 1  # the next item's bare 「N番」 announcement belongs to the next clip
            next_start = segments[following]["start"] - LEAD_IN
        # Recognition sometimes drops the 「N番」 announcement and first words; then start earlier (into the silence).
        lead_in = LEAD_IN if marker_number(segments[first]["text"]) else MISSED_ANNOUNCEMENT_LEAD_IN
        previous_end = bounds[-1][1] if bounds else 0.0
        start = max(segments[first]["start"] - lead_in, previous_end, 0.0)
        end = min(segments[following - 1]["end"] + TAIL, next_start, duration)
        bounds.append((round(start, 2), round(end, 2)))
    return bounds


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    problems = 0
    for path in sorted((OFFICIAL_DIR / "questions").glob("*.json")):
        questions = json.loads(path.read_text(encoding="utf-8"))
        listening = [question for question in questions if question.get("official", {}).get("part") == "listening"]
        groups: dict[tuple[str, int], list[dict]] = {}
        for question in listening:
            groups.setdefault((question["official"]["set"], question["official"]["mondai"]), []).append(question)
        file_ok = True
        for (official_set, mondai), items in sorted(groups.items()):
            transcript = json.loads((OFFICIAL_DIR / "audio_segments" / f"{official_set}_N2Q{mondai}.json").read_text(encoding="utf-8"))
            segments = transcript["segments"]
            first_by_number: dict[int, dict] = {}
            for question in sorted(items, key=lambda item: item["official"]["number"]):
                first_by_number.setdefault(item_number(question), question)
            targets = [(number, opening(question)) for number, question in sorted(first_by_number.items())]
            starts, item_scores = align(segments, targets)
            weak = [(number, round(value, 2)) for (number, _), value in zip(targets, item_scores) if value < MIN_SCORE]
            if weak:
                print(f"WEAK {official_set} 問題{mondai}: items with low match scores {weak}")
                problems += 1
                file_ok = False
                continue
            spans = dict(zip([number for number, _ in targets], clip_bounds(segments, starts, transcript["duration"])))
            for question in items:
                start, end = spans[item_number(question)]
                question["audio"] = {"file": f"raw/{official_set}/N2Q{mondai}.mp3", "start": start, "end": end}
                print(f"{question['id']:14} {strip_markup(question['question']):10} {start:7.1f} - {end:7.1f} ({end - start:5.1f}s)")
        if listening and file_ok and not dry_run:
            path.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
