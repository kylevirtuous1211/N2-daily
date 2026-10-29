"""Pick N2 words that the question bank does not test yet, with a suggested question type each.

Usage: python tools/pick_words.py COUNT [--seed N] [--out words.json]

Word list: content/wordlists/n2_waller.csv, Jonathan Waller's JLPT N2 list (CC BY,
http://www.tanos.co.uk/jlpt/) via https://github.com/jamsinclair/open-anki-jlpt-decks (MIT).
JLPT has published no official word list since 2010, so this is an unofficial estimate.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
APP_DIR = Path(__file__).resolve().parent.parent
WORDLIST = APP_DIR / "content" / "wordlists" / "n2_waller.csv"
KANJI = re.compile(r"[\u3400-\u9fff]")
KANJI_TYPES = ["kanji_reading", "orthography", "context", "paraphrase", "usage"]
KANA_TYPES = ["context", "paraphrase", "usage"]


def bank_words() -> set[str]:
    words = set()
    for path in (APP_DIR / "content" / "questions").glob("*.json"):
        for question in json.loads(path.read_text(encoding="utf-8")):
            words.update(entry["word"] for entry in question["vocab"])
            if question.get("target_word"):
                words.add(question["target_word"])
    return words


def clean_entries() -> list[dict]:
    entries = []
    for row in csv.DictReader(WORDLIST.open(encoding="utf-8")):
        word, reading = row["expression"].strip(), row["reading"].strip()
        if re.search(r"[〜～()（）;；,、/]", word + reading) or " " in word:
            continue  # fragments such as 「〜 (まる) ごと」 or entries with alternatives
        entries.append({"word": word, "reading": reading, "meaning": row["meaning"].strip()})
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("count", type=int)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    covered = bank_words()
    candidates = [entry for entry in clean_entries() if entry["word"] not in covered]
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    picked = candidates[:args.count]
    kanji_turn = kana_turn = 0
    for entry in picked:
        if KANJI.search(entry["word"]):
            entry["section"] = KANJI_TYPES[kanji_turn % len(KANJI_TYPES)]
            kanji_turn += 1
        else:
            entry["section"] = KANA_TYPES[kana_turn % len(KANA_TYPES)]
            kana_turn += 1
    print(f"{len(candidates)} uncovered clean words; picked {len(picked)}", file=sys.stderr)
    text = json.dumps(picked, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
