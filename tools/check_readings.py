"""Cross-check every furigana reading and vocab reading against JMdict and KANJIDIC2.

Usage: python tools/check_readings.py [--json report.json]

Needs the jmdict-simplified JSON files in cache/ (jmdict-eng-*.json, kanjidic2-en-*.json) from
https://github.com/scriptin/jmdict-simplified/releases (EDRDG data, CC BY-SA 4.0).

A reading is accepted when JMdict lists it for the exact word, or when the text can be split into
JMdict words / single kanji (KANJIDIC on/kun readings incl. rendaku and small-tsu variants) / kana
whose readings concatenate to it. Everything else is reported for human review. A reading for a
multi-character word that JMdict knows, but without that reading, is reported as "not-listed".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from n2.bank import KANJI_RUN_AT_END, RUBY_PATTERN  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = APP_DIR / "cache"
BANK_DIRS = [APP_DIR / "content" / "questions", APP_DIR / "content" / "official" / "questions"]
TEXT_FIELDS = ("question", "passage", "full_sentence", "script")
MAX_PIECE = 8

RENDAKU = str.maketrans("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HANDAKU = str.maketrans("はひふへほ", "ぱぴぷぺぽ")
GEMINATE_ENDINGS = ("つ", "く", "ち", "き")


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in text)


def is_kana(char: str) -> bool:
    return "ぁ" <= char <= "ゟ" or "゠" <= char <= "ヿ"


def reading_variants(reading: str, voiced: bool) -> set[str]:
    """Sound changes inside compounds: rendaku/handakuten (not at the start of a word) and small-tsu."""
    variants = {reading}
    if voiced:
        variants |= {reading[:1].translate(RENDAKU) + reading[1:], reading[:1].translate(HANDAKU) + reading[1:]}
    for base in list(variants):
        if len(base) > 1 and base.endswith(GEMINATE_ENDINGS):
            variants.add(base[:-1] + "っ")
        if base.endswith("じゅう"):  # 十 before p/k/s/t sounds: じゅっ (十分 じゅっぷん, 五十ページ ごじゅっページ)
            variants |= {base[:-2] + "ゅっ", base[:-3] + "じっ"}
    return {variant for variant in variants if variant}


class Dictionary:
    def __init__(self):
        jmdict_path = next(CACHE_DIR.glob("jmdict-eng-*.json"), None)
        kanjidic_path = next(CACHE_DIR.glob("kanjidic2-en-*.json"), None)
        if not jmdict_path or not kanjidic_path:
            raise SystemExit(f"Missing JMdict/KANJIDIC2 JSON in {CACHE_DIR}; see the module docstring.")
        self.words: dict[str, set[str]] = {}
        for entry in json.loads(jmdict_path.read_text(encoding="utf-8"))["words"]:
            kanji_forms = [form["text"] for form in entry["kanji"]]
            for kana in entry["kana"]:
                reading = to_hiragana(kana["text"])
                applies = kanji_forms if kana["appliesToKanji"] == ["*"] else kana["appliesToKanji"]
                for form in applies:
                    self.words.setdefault(form, set()).add(reading)
                self.words.setdefault(kana["text"], set()).add(reading)
        self.kanji: dict[str, set[str]] = {}
        for character in json.loads(kanjidic_path.read_text(encoding="utf-8"))["characters"]:
            readings: set[str] = set()
            for group in (character.get("readingMeaning") or {}).get("groups", []):
                for item in group["readings"]:
                    if item["type"] not in ("ja_on", "ja_kun"):
                        continue
                    value = to_hiragana(item["value"]).strip("-")
                    readings.add(value.split(".")[0])
                    readings.add(value.replace(".", ""))
            for nanori in (character.get("readingMeaning") or {}).get("nanori", []):
                readings.add(to_hiragana(nanori))
            self.kanji[character["literal"]] = {reading for reading in readings if reading}

        # Kanji stem of okurigana words (流行る -> 流行) -> full readings, for runs like 流行{はや}る.
        self.stems: dict[str, set[str]] = {}
        for form, readings in self.words.items():
            stem = re.sub(r"[ぁ-ゟ]+$", "", form)
            if stem != form and stem and not is_kana(stem[-1]):
                self.stems.setdefault(stem, set()).update(readings)

    def piece_readings(self, text: str, start: int, length: int, word_internal: bool, words_only: bool) -> set[str]:
        piece = text[start:start + length]
        readings = set(self.words.get(piece, ()))
        if piece == "ヶ":  # counter mark: 3ヶ月 さんかげつ, 2ヶ所 にかしょ
            readings |= {"か", "が", "こ"}
        if length == 1 and not words_only:
            char = text[start - 1] if piece == "々" and start > 0 else piece
            readings |= self.kanji.get(char, set()) | self.words.get(char, set())
        voiced = start > 0 or word_internal
        return {variant for reading in readings for variant in reading_variants(reading, voiced)}

    def explains(self, text: str, reading: str, word_internal: bool = False, words_only: bool = False) -> bool:
        """Can `reading` be built from the pieces of `text`? words_only: only multi-character JMdict words."""
        text, reading = text.strip(), to_hiragana(reading.strip())

        @lru_cache(maxsize=None)
        def walk(position: int, offset: int) -> bool:
            if position == len(text):
                return offset == len(reading)
            char = text[position]
            if (is_kana(char) and char != "ヶ") or char == "ー":
                return offset < len(reading) and to_hiragana(char) == reading[offset] and walk(position + 1, offset + 1)
            for length in range(min(MAX_PIECE, len(text) - position), 0, -1):
                for option in self.piece_readings(text, position, length, word_internal, words_only):
                    if reading.startswith(option, offset) and walk(position + length, offset + len(option)):
                        return True
            return False

        return walk(0, 0)

    def okurigana_split(self, base: str, reading: str, before: str) -> bool:
        """Run is the kanji part of a word whose kana sits outside the braces (流行{はや}る, お腹{なか})."""
        reading = to_hiragana(reading)
        if any(full.startswith(reading) and len(full) > len(reading) for full in self.stems.get(base, ())):
            return True
        if before and is_kana(before):
            prefix = to_hiragana(before)
            return prefix + reading in self.words.get(before + base, ())
        return False


def ruby_runs(text: str):
    """Yield (kanji run, reading, character just before the run)."""
    cleaned = re.sub(r"\{\{\d\}\}", "", text).replace("[[", "").replace("]]", "")
    position = 0
    for match in RUBY_PATTERN.finditer(cleaned):
        segment = cleaned[position:match.start()]
        run = KANJI_RUN_AT_END.search(segment)
        if run:
            # "}" marks a run that directly follows another run, i.e. one compound split in two (旅行{りょこう}会社{がいしゃ}).
            before = segment[:run.start()][-1:] or ("}" if position > 0 and run.start() == 0 else "")
            yield run.group(0), match.group(1), before
        position = match.end()


def normalize_word(word: str) -> str:
    """Headword without notes; empty for grammar-like patterns such as とても〜ない."""
    word = re.split(r"[（(／/]", word)[0].strip().strip("〜～~？！?!。、").strip()
    return "" if any(mark in word for mark in "〜～~…") else word


def follows_word_part(before: str) -> bool:
    """A run right after kana or a digit can be the inside of a word (ゴミ袋, 引っ張る, 10分), so rendaku is allowed."""
    return bool(before) and (is_kana(before) or before in "ー}" or before.isdigit())


def check_run(dictionary: Dictionary, base: str, reading: str, before: str) -> str | None:
    word_internal = follows_word_part(before)
    if dictionary.okurigana_split(base, reading, before):
        return None
    known = dictionary.words.get(base)
    if known and len(base) > 1:
        # A known word must use one of its own readings (so 慎重{しんじゅう} is caught even though 重 can be じゅう),
        # unless it is a compound of other JMdict words (百歳 = 百 + 歳).
        listed = {variant for option in known for variant in reading_variants(option, word_internal)}
        if to_hiragana(reading) in listed or dictionary.explains(base, reading, word_internal, words_only=True):
            return None
        return "not-listed"
    return None if dictionary.explains(base, reading, word_internal=word_internal) else "unexplained"


def check_headword(dictionary: Dictionary, word: str, reading: str) -> str | None:
    """A vocab headword: if JMdict knows the word it must list the reading (or be a clean compound of JMdict words)."""
    known = dictionary.words.get(word)
    if known and len(word) > 1 and to_hiragana(reading) not in known:
        return None if dictionary.explains(word, reading, words_only=True) else "not-listed"
    return None if dictionary.explains(word, reading) else "unexplained"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, help="write the full report as JSON")
    parser.add_argument("--fail-on-findings", action="store_true", help="exit 1 if anything needs review")
    args = parser.parse_args()

    dictionary = Dictionary()
    findings = []
    checked = 0
    for directory in BANK_DIRS:
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            for question in json.loads(path.read_text(encoding="utf-8")):
                texts = [(field, question.get(field)) for field in TEXT_FIELDS]
                texts += [(f"choices[{index}]", choice) for index, choice in enumerate(question.get("choices", []))]
                texts += [(f"vocab[{index}].example", entry.get("example")) for index, entry in enumerate(question.get("vocab", []))]
                texts += [(f"grammar[{index}].example", entry.get("example")) for index, entry in enumerate(question.get("grammar", []))]
                for field, text in texts:
                    affix_choice = question.get("section") == "word_formation" and field.startswith("choices")
                    for base, reading, before in ruby_runs(text or ""):
                        checked += 1
                        # 語形成 choices are prefixes/suffixes shown as they sound inside a compound (水浸し -> 浸{びた}し).
                        problem = check_run(dictionary, base, reading, "}" if affix_choice else before)
                        if problem:
                            findings.append({"id": question["id"], "field": field, "text": base, "reading": reading,
                                             "problem": problem, "jmdict": sorted(dictionary.words.get(base, ()))})
                for index, entry in enumerate(question.get("vocab", [])):
                    word, reading = normalize_word(entry.get("word", "")), entry.get("reading", "")
                    if not word or not reading or all(is_kana(char) or char == "ー" for char in word):
                        continue
                    checked += 1
                    problem = check_headword(dictionary, word, reading)
                    if problem:
                        findings.append({"id": question["id"], "field": f"vocab[{index}]", "text": word, "reading": reading,
                                         "problem": problem, "jmdict": sorted(dictionary.words.get(word, ()))})

    for finding in findings:
        listed = f"  JMdict: {', '.join(finding['jmdict'])}" if finding["jmdict"] else ""
        print(f"{finding['problem']:12} {finding['id']:14} {finding['field']:20} {finding['text']}{{{finding['reading']}}}{listed}")
    print(f"{checked} readings checked, {len(findings)} to review")
    if args.json:
        args.json.write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if args.fail_on_findings and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
