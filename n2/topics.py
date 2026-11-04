"""Topic groups for deck cards.

Every vocabulary word in the question banks is labeled with one topic from a fixed list (content/topics.json),
so related words can be studied together.  Topics marked "grammatical" (verb groups, adjectives, ...) are the
fallback for words with no clear subject; their label must match the word's part of speech.  Within a topic,
cards are ordered by romaji and split into groups of GROUP_SIZE.
"""

from __future__ import annotations

import json
from pathlib import Path

TOPICS_FILE = Path(__file__).resolve().parent.parent / "content" / "topics.json"
GROUP_SIZE = 10
GRAMMAR_TOPIC = "grammar"
# Part-of-speech words (as written in the banks' "pos" field) that allow each grammatical fallback topic.
GRAMMATICAL_POS = {
    "godan": ("godan verb",),
    "ichidan": ("ichidan verb",),
    "suru": ("suru verb",),
    "adjective": ("adjective",),
    "adverb": ("adverb",),
    "function": ("conjunction", "particle", "prefix", "suffix", "counter", "pronoun", "auxiliary", "expression",
                 "pre-noun", "interjection"),
}
FALLBACK_ORDER = ("godan", "ichidan", "suru", "adjective", "adverb", "function")


class Topics:
    def __init__(self, topics: list[dict], words: dict[str, str]):
        self.topics = {topic["id"]: topic for topic in topics}
        self.rank = {topic["id"]: index for index, topic in enumerate(topics)}
        self.words = words
        self.fallbacks = {topic["grammatical"]: topic["id"] for topic in topics if topic.get("grammatical")}

    @classmethod
    def load(cls, main_file: Path, official_file: Path | None = None) -> "Topics":
        document = json.loads(main_file.read_text(encoding="utf-8"))
        words = dict(document.get("words", {}))
        if official_file is not None and official_file.is_file():
            words.update(json.loads(official_file.read_text(encoding="utf-8")).get("words", {}))
        return cls(document["topics"], words)

    def label_problems(self, key: str, pos: str, topic: str | None) -> list[str]:
        """Why `topic` is not a valid label for the word `key` (word:reading) with part of speech `pos`."""
        if topic is None:
            return [f"{key}: no topic"]
        if topic not in self.topics or topic == GRAMMAR_TOPIC:
            return [f"{key}: unknown topic {topic!r}"]
        grammatical = self.topics[topic].get("grammatical")
        if grammatical and not any(part in pos.lower() for part in GRAMMATICAL_POS[grammatical]):
            return [f"{key}: topic {topic!r} does not fit part of speech {pos!r}"]
        return []

    def topic_for(self, kind: str, data: dict) -> str:
        if kind != "vocab":
            return GRAMMAR_TOPIC
        labeled = self.words.get(f"{data.get('word')}:{data.get('reading')}")
        if labeled in self.topics:
            return labeled
        pos = str(data.get("pos", "")).lower()
        for grammatical in FALLBACK_ORDER:
            if any(part in pos for part in GRAMMATICAL_POS[grammatical]):
                return self.fallbacks[grammatical]
        return self.fallbacks["function"]

    def describe(self, topic_id: str) -> dict:
        topic = self.topics[topic_id]
        return {"id": topic_id, "ja": topic["ja"], "en": topic["en"]}


def sort_text(kind: str, data: dict) -> str:
    text = data.get("reading") if kind == "vocab" else data.get("pattern")
    return romaji(str(text or ""))


def assign_groups(cards: list[dict], topics: Topics) -> None:
    """Give each card view a "topic" and a "group" (topic split into romaji-ordered runs of GROUP_SIZE), in place."""
    by_topic: dict[str, list[dict]] = {}
    for card in cards:
        topic_id = topics.topic_for(card["kind"], card["data"])
        card["topic"] = topics.describe(topic_id)
        card["sort_key"] = sort_text(card["kind"], card["data"])
        by_topic.setdefault(topic_id, []).append(card)
    for topic_id, members in by_topic.items():
        members.sort(key=lambda card: (card["sort_key"], card["key"]))
        parts = -(-len(members) // GROUP_SIZE)
        for index, card in enumerate(members):
            part = index // GROUP_SIZE + 1
            card["group"] = {"id": f"{topic_id}-{part}", "part": part, "parts": parts,
                             "order": topics.rank[topic_id] * 1000 + part}


# --- romaji (Hepburn) -----------------------------------------------------------

_KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko", "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so", "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to", "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho", "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n", "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o", "ゎ": "wa",
}
_SMALL_Y = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
_SMALL_VOWELS = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}


def _to_hiragana(text: str) -> str:
    return "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in text)


def romaji(text: str) -> str:
    """Hepburn romaji of the kana in `text` (other characters dropped, except ASCII letters and digits)."""
    kana = _to_hiragana(text)
    output: list[str] = []
    double_next = False
    for char in kana:
        if char == "っ":
            double_next = True
            continue
        if char in _SMALL_Y and output and output[-1].endswith("i"):
            stem = output.pop()[:-1]  # き + ゃ = kya, し + ゃ = sha, ち + ゃ = cha, じ + ゃ = ja
            syllable = stem + ("" if stem.endswith(("sh", "ch", "j")) else "y") + _SMALL_Y[char]
        elif char in _SMALL_VOWELS and output and output[-1] in ("fu", "te", "de", "u", "vu", "chi", "shi", "ji", "tsu"):
            previous = output.pop()
            stem = {"fu": "f", "te": "t", "de": "d", "u": "w", "vu": "v", "tsu": "ts"}.get(previous, previous[:-1])
            syllable = stem + _SMALL_VOWELS[char]
        elif char == "ー":
            vowel = next((letter for letter in reversed("".join(output)) if letter in "aeiou"), "")
            syllable = vowel
        elif char in _KANA:
            syllable = _KANA[char]
        elif char.isascii() and char.isalnum():
            syllable = char.lower()
        else:
            continue
        if double_next and syllable and syllable[0] not in "aeiouny":
            syllable = ("t" if syllable.startswith("ch") else syllable[0]) + syllable
        double_next = False
        output.append(syllable)
    return "".join(output)


def vocab_entries(questions: list[dict]) -> dict[str, str]:
    """word:reading -> part of speech, for every vocabulary entry in `questions`.

    The same word can be glossed with different parts of speech in different questions (ただ: conjunction or
    adverb); they are joined, so a label only has to fit one of them.
    """
    words: dict[str, list[str]] = {}
    for question in questions:
        for entry in question.get("vocab", []):
            variants = words.setdefault(f"{entry['word']}:{entry['reading']}", [])
            if str(entry.get("pos", "")) not in variants:
                variants.append(str(entry.get("pos", "")))
    return {key: " / ".join(variants) for key, variants in words.items()}


def coverage_problems(topics: Topics, questions: list[dict], labels: dict[str, str]) -> list[str]:
    """Every word in `questions` needs a valid label in `labels`, and every label in `labels` needs a word."""
    words = vocab_entries(questions)
    problems = [problem for key, pos in sorted(words.items())
                for problem in topics.label_problems(key, pos, labels.get(key))]
    problems += [f"{key}: labeled but not in the question bank" for key in sorted(labels.keys() - words.keys())]
    return problems
