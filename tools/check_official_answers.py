"""Compare every official question's answer with the official answer key (正答表).

Usage:
    uv run --with pymupdf python tools/check_official_answers.py

Reads content/official/raw/<set>/N2answer.pdf (text layer), parses it, and checks that
answer + 1 equals the key for every item in content/official/questions. Exits 1 on any mismatch
or on an item missing from either side.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
OFFICIAL_DIR = Path(__file__).resolve().parent.parent / "content" / "official"
DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def parse_key(pdf: Path) -> dict[tuple[str, int, int], int]:
    """{(part, mondai, number): answer}; language numbers are booklet numbers, listening numbers count within a 問題."""
    with pymupdf.open(pdf) as document:
        tokens = [token.strip().translate(DIGITS) for page in document for token in page.get_text().split("\n")]
    # 2012 prints 問題5 3番's sub-questions as one token 「質問1 質問2」; 2018 prints (1) (2).
    tokens = [re.sub(r"質問\s*(\d)", r"(\1)", part) for token in tokens if token
              for part in (token.split() if "質問" in token else [token])]
    key: dict[tuple[str, int, int], int] = {}
    listening_seen = False
    next_language = 1
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith("●聴"):
            listening_seen = True
        header = re.fullmatch(r"問題\s*(\d+)", token)
        if not header:
            continue
        mondai = int(header.group(1))
        part = "listening" if listening_seen and mondai <= 5 else "language"
        next_listening = 1  # rows can wrap, so the expected label carries over between rows of one 問題
        while index < len(tokens):
            labels = []
            while index < len(tokens):
                label = tokens[index]
                numbered = [item for item in labels if item.isdigit()]
                if part == "language" and label == str(next_language + len(labels)):
                    labels.append(label)
                elif part == "listening" and (label in ("例", "(1)", "(2)") or
                                              (label == str(next_listening + len(numbered))
                                               and not any(item.startswith("(") for item in labels))):
                    labels.append(label)
                else:
                    break
                index += 1
            next_listening += len([item for item in labels if item.isdigit()])
            if "(1)" in labels:  # 「3 (1) (2)」: the 3 only heads its two sub-questions and has no answer of its own
                del labels[labels.index("(1)") - 1]
            if not labels:
                break
            answers = tokens[index:index + len(labels)]
            index += len(labels)
            number = len([existing for existing in key if existing[:2] == (part, mondai)])
            for label, answer in zip(labels, answers):
                if label == "例":
                    continue
                if part == "language":
                    key[(part, mondai, int(label))] = int(answer)
                    next_language = int(label) + 1
                else:
                    number += 1
                    key[(part, mondai, number)] = int(answer)
            if index >= len(tokens) or re.fullmatch(r"問題\s*\d+", tokens[index]) or tokens[index].startswith("●"):
                break
    return key


def main() -> int:
    mismatches = 0
    for set_dir in sorted(path for path in (OFFICIAL_DIR / "raw").iterdir() if path.is_dir()):
        official_set = set_dir.name
        key = parse_key(set_dir / "N2answer.pdf")
        ours: dict[tuple[str, int, int], tuple[str, int]] = {}
        for path in sorted((OFFICIAL_DIR / "questions").glob(f"{official_set}_*.json")):
            for question in json.loads(path.read_text(encoding="utf-8")):
                meta = question["official"]
                ours[(meta["part"], meta["mondai"], meta["number"])] = (question["id"], question["answer"] + 1)
        for item in sorted(set(key) | set(ours)):
            if item not in ours:
                print(f"MISSING in bank {official_set} {item}")
                mismatches += 1
            elif item not in key:
                print(f"MISSING in key  {official_set} {item} ({ours[item][0]})")
                mismatches += 1
            elif key[item] != ours[item][1]:
                print(f"MISMATCH {ours[item][0]}: bank {ours[item][1]}, key {key[item]}")
                mismatches += 1
        print(f"{official_set}: {len(key)} key items, {len(ours)} bank items")
    print("all answers match the official keys" if not mismatches else f"{mismatches} problems")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
