"""Question bank: section metadata, loading, and validation.

Markup used in all Japanese text fields:
    漢字{かんじ}   furigana over the run of kanji directly before the braces
    [[...]]        underlined target (may contain furigana markup)
    {{1}}..{{4}}   answer slots in sentence_order questions
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SECTIONS = {
    "kanji_reading": {
        "ja": "漢字読み", "en": "Kanji reading",
        "instructions": "＿＿＿の言葉の読み方として最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "orthography": {
        "ja": "表記", "en": "Writing in kanji",
        "instructions": "＿＿＿の言葉を漢字で書くとき、最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "word_formation": {
        "ja": "語形成", "en": "Word formation",
        "instructions": "（　　）に入れるのに最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "context": {
        "ja": "文脈規定", "en": "Vocabulary in context",
        "instructions": "（　　）に入れるのに最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "paraphrase": {
        "ja": "言い換え類義", "en": "Paraphrase",
        "instructions": "＿＿＿の言葉に意味が最も近いものを、１・２・３・４から一つ選びなさい。",
    },
    "usage": {
        "ja": "用法", "en": "Usage",
        "instructions": "次の言葉の使い方として最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "grammar_form": {
        "ja": "文法形式の判断", "en": "Grammar form",
        "instructions": "次の文の（　　）に入れるのに最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "sentence_order": {
        "ja": "文の組み立て", "en": "Sentence building",
        "instructions": "次の文の ★ に入る最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "reading": {
        "ja": "読解", "en": "Reading comprehension",
        "instructions": "次の文章を読んで、後の問いに対する答えとして最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "text_grammar": {
        "ja": "文章の文法", "en": "Grammar in a passage",
        "instructions": "次の文章を読んで、文章全体の内容を考えて、（　　）の中に入る最もよいものを、１・２・３・４から一つ選びなさい。",
    },
    "listening_task": {
        "ja": "課題理解", "en": "Listening: task-based",
        "instructions": "まず質問を聞いてください。それから話を聞いて、問題用紙の１から４の中から、最もよいものを一つ選んでください。",
    },
    "listening_point": {
        "ja": "ポイント理解", "en": "Listening: key points",
        "instructions": "まず質問を聞いてください。そのあと、問題用紙のせんたくしを読んでください。読む時間があります。それから話を聞いて、問題用紙の１から４の中から、最もよいものを一つ選んでください。",
    },
    "listening_summary": {
        "ja": "概要理解", "en": "Listening: overview",
        "instructions": "問題用紙に何もいんさつされていません。全体としてどんな内容かを聞く問題です。話の前に質問はありません。まず話を聞いてください。それから、質問とせんたくしを聞いて、１から４の中から、最もよいものを一つ選んでください。",
    },
    "listening_response": {
        "ja": "即時応答", "en": "Listening: quick response",
        "instructions": "問題用紙に何もいんさつされていません。まず文を聞いてください。それから、それに対する返事を聞いて、１から３の中から、最もよいものを一つ選んでください。",
    },
    "listening_integrated": {
        "ja": "統合理解", "en": "Listening: integrated",
        "instructions": "長めの話を聞きます。問題用紙にメモをとってもかまいません。質問とせんたくしを聞いて、１から４の中から、最もよいものを一つ選んでください。",
    },
}

LISTENING_SECTIONS = ("listening_task", "listening_point", "listening_summary", "listening_response", "listening_integrated")

# Questions per section in a standard daily mini test (20 questions).
MINI_TEST_PLAN = {
    "kanji_reading": 3,
    "orthography": 2,
    "word_formation": 1,
    "context": 3,
    "paraphrase": 2,
    "usage": 1,
    "grammar_form": 4,
    "sentence_order": 2,
    "reading": 2,
}

KANJI_CHARS = "㐀-䶿一-鿿豈-﫿々〆ヶ"
KANA_READING = re.compile(r"^[ぁ-ゟ゠-ヿー]+$")
RUBY_PATTERN = re.compile(r"\{([^{}]*)\}")
KANJI_RUN_AT_END = re.compile(f"[{KANJI_CHARS}]+$")

TEXT_FIELDS = ("question", "passage", "full_sentence", "script")


@dataclass
class ValidationError:
    question_id: str
    message: str

    def __str__(self) -> str:
        return f"{self.question_id}: {self.message}"


def strip_markup(text: str) -> str:
    text = text.replace("[[", "").replace("]]", "")
    text = re.sub(r"\{\{\d\}\}", "＿＿", text)
    return RUBY_PATTERN.sub("", text)


def markup_errors(text: str) -> list[str]:
    """Return problems with furigana/target markup in a single text field."""
    errors: list[str] = []
    if text.count("[[") != text.count("]]"):
        errors.append(f"unbalanced [[ ]] in {text!r}")
    without_slots = re.sub(r"\{\{\d\}\}", "", text)
    position = 0
    for match in RUBY_PATTERN.finditer(without_slots):
        reading = match.group(1)
        before = without_slots[position:match.start()].replace("[[", "").replace("]]", "")
        if not KANA_READING.match(reading):
            errors.append(f"furigana {reading!r} is not kana")
        if not KANJI_RUN_AT_END.search(before):
            errors.append(f"furigana {{{reading}}} is not preceded by kanji in {text!r}")
        position = match.end()
    leftover = RUBY_PATTERN.sub("", without_slots)
    if "{" in leftover or "}" in leftover:
        errors.append(f"stray brace in {text!r}")
    return errors


def validate_question(question: dict) -> list[ValidationError]:
    question_id = question.get("id", "<missing id>")
    problems: list[str] = []

    def require(field: str, kind: type) -> None:
        if not isinstance(question.get(field), kind):
            problems.append(f"field {field!r} must be {kind.__name__}")

    require("id", str)
    require("section", str)
    require("question", str)
    require("choices", list)
    require("answer", int)
    require("translation", str)
    require("explanation", str)
    require("choice_notes", list)
    require("vocab", list)
    if problems:
        return [ValidationError(question_id, problem) for problem in problems]

    section = question["section"]
    if section not in SECTIONS:
        problems.append(f"unknown section {section!r}")

    choices = question["choices"]
    choice_count = 3 if section == "listening_response" else 4
    if len(choices) != choice_count or not all(isinstance(choice, str) and choice.strip() for choice in choices):
        problems.append(f"need exactly {choice_count} non-empty choices")
    elif len({strip_markup(choice) for choice in choices}) != choice_count:
        problems.append("choices must be distinct")
    if not 0 <= question["answer"] < choice_count:
        problems.append(f"answer must be 0-{choice_count - 1}")
    if len(question["choice_notes"]) != choice_count:
        problems.append(f"need exactly {choice_count} choice_notes")

    if section in ("kanji_reading", "orthography", "paraphrase") and "[[" not in question["question"]:
        problems.append("question must mark the target with [[ ]]")
    if section == "kanji_reading":
        for target in re.findall(r"\[\[(.*?)\]\]", question["question"]):
            if "{" in target:
                problems.append("kanji_reading target must not carry furigana (it reveals the answer)")
    if section == "orthography" and any("{" in choice for choice in choices if isinstance(choice, str)):
        problems.append("orthography choices must not carry furigana (it reveals the answer)")
    if section in ("word_formation", "context", "grammar_form") and "（　　）" not in question["question"]:
        problems.append("question must contain the blank （　　）")
    if section in ("reading", "text_grammar"):
        has_image = isinstance(question.get("passage_image"), str)
        if not has_image and (not isinstance(question.get("passage"), str) or len(strip_markup(question["passage"])) < 80):
            problems.append(f"{section} needs a passage of at least 80 characters (or a passage_image)")
        if not isinstance(question.get("passage_translation"), str):
            problems.append(f"{section} needs passage_translation")
    if section in LISTENING_SECTIONS:
        for field in ("script", "script_translation"):
            if not isinstance(question.get(field), str) or not question[field].strip():
                problems.append(f"listening needs {field}")
    if section == "sentence_order":
        problems.extend(_sentence_order_problems(question))
    if section in ("word_formation", "context", "grammar_form", "sentence_order"):
        if not isinstance(question.get("full_sentence"), str):
            problems.append("needs full_sentence (the completed correct sentence)")

    for field in TEXT_FIELDS:
        if isinstance(question.get(field), str):
            problems.extend(markup_errors(question[field]))
    for choice in choices:
        if isinstance(choice, str):
            problems.extend(markup_errors(choice))

    if not question["vocab"]:
        problems.append("vocab list must not be empty")
    for entry in question["vocab"]:
        problems.extend(_vocab_problems(entry))
    for entry in question.get("grammar", []):
        problems.extend(_grammar_problems(entry))

    return [ValidationError(question_id, problem) for problem in problems]


def _sentence_order_problems(question: dict) -> list[str]:
    problems = []
    slots = re.findall(r"\{\{(\d)\}\}", question["question"])
    if slots != ["1", "2", "3", "4"]:
        problems.append("sentence_order question needs slots {{1}}..{{4}} in order")
    star = question.get("star")
    if star not in (1, 2, 3, 4):
        problems.append("sentence_order needs star (1-4)")
    order = question.get("correct_order")
    if not isinstance(order, list) or sorted(order) != [0, 1, 2, 3]:
        problems.append("sentence_order needs correct_order, a permutation of [0,1,2,3]")
    elif star in (1, 2, 3, 4) and order[star - 1] != question["answer"]:
        problems.append("answer must equal correct_order[star - 1]")
    return problems


def _vocab_problems(entry: dict) -> list[str]:
    problems = []
    for field in ("word", "reading", "meaning", "pos", "example", "example_translation"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            problems.append(f"vocab {entry.get('word')!r} missing {field}")
    if isinstance(entry.get("reading"), str) and not KANA_READING.match(entry["reading"]):
        problems.append(f"vocab {entry.get('word')!r} reading must be kana")
    if isinstance(entry.get("example"), str):
        problems.extend(markup_errors(entry["example"]))
    return problems


def _grammar_problems(entry: dict) -> list[str]:
    problems = []
    for field in ("pattern", "meaning", "formation", "example", "example_translation"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            problems.append(f"grammar {entry.get('pattern')!r} missing {field}")
    if isinstance(entry.get("example"), str):
        problems.extend(markup_errors(entry["example"]))
    return problems


OFFICIAL_PARTS = {
    "language": {"ja": "言語知識（文字・語彙・文法）・読解", "minutes": 105},
    "listening": {"ja": "聴解", "minutes": 50},
}


class QuestionBank:
    """Daily-test pool plus (optionally) official practice tests, which never enter the daily pool."""

    def __init__(self, questions: list[dict], official: list[dict] | None = None, warnings: list[str] | None = None):
        self.questions = questions
        self.official = official or []
        self.warnings = warnings or []
        self.by_id = {question["id"]: question for question in self.questions + self.official}
        self.by_section: dict[str, list[dict]] = {section: [] for section in SECTIONS}
        for question in questions:
            self.by_section[question["section"]].append(question)
        self.official_sets: dict[str, dict[str, list[dict]]] = {}
        for question in sorted(self.official, key=_official_sort_key):
            meta = question["official"]
            self.official_sets.setdefault(meta["set"], {}).setdefault(meta["part"], []).append(question)

    @classmethod
    def load(cls, directory: Path, official_directory: Path | None = None) -> "QuestionBank":
        questions, errors = load_and_validate(directory)
        if errors:
            details = "\n".join(str(error) for error in errors[:20])
            raise ValueError(f"{len(errors)} problems in question bank:\n{details}")

        # The official bank is optional and imported locally; a broken import must not stop the app,
        # and a partial official test must never be served, so any error disables the whole official bank.
        official: list[dict] = []
        warnings: list[str] = []
        if official_directory is not None and official_directory.is_dir():
            official, official_errors = load_and_validate(official_directory, official=True)
            duplicates = {question["id"] for question in questions} & {question["id"] for question in official}
            official_errors += [ValidationError(question_id, "id used in both banks") for question_id in sorted(duplicates)]
            if official_errors:
                warnings = [f"official tests disabled: {len(official_errors)} problems, first: {official_errors[0]}"]
                official = []
        return cls(questions, official, warnings)


def _official_sort_key(question: dict) -> tuple:
    meta = question["official"]
    return (meta["set"], meta["part"], meta["mondai"], meta["number"])


def official_problems(question: dict, assets_root: Path, require_audio: bool = True) -> list[str]:
    problems = []
    meta = question.get("official")
    if not isinstance(meta, dict):
        return ["official question needs an 'official' object"]
    if not isinstance(meta.get("set"), str) or meta.get("part") not in OFFICIAL_PARTS:
        problems.append("official.set must be a string and official.part one of " + ", ".join(OFFICIAL_PARTS))
    if not isinstance(meta.get("mondai"), int) or not isinstance(meta.get("number"), int):
        problems.append("official.mondai and official.number must be integers")
    for field in ("passage_image", "question_image"):
        if field in question and not (assets_root / question[field]).is_file():
            problems.append(f"{field} file not found: {question[field]}")
    audio = question.get("audio")
    if audio is not None:
        if not isinstance(audio, dict) or not (assets_root / str(audio.get("file"))).is_file():
            problems.append("audio.file not found")
        elif not (isinstance(audio.get("start"), (int, float)) and isinstance(audio.get("end"), (int, float))
                  and 0 <= audio["start"] < audio["end"]):
            problems.append("audio needs numeric start < end")
    if require_audio and question.get("section") in LISTENING_SECTIONS and audio is None:
        problems.append("listening question needs audio")
    return problems


def load_and_validate(directory: Path, official: bool = False) -> tuple[list[dict], list[ValidationError]]:
    """Official banks live in content/official/questions; their assets are resolved against content/official."""
    questions: list[dict] = []
    errors: list[ValidationError] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(ValidationError(path.name, f"invalid JSON: {error}"))
            continue
        if not isinstance(items, list):
            errors.append(ValidationError(path.name, "file must contain a JSON list"))
            continue
        for item in items:
            item_errors = validate_question(item)
            if official:
                item_errors += [ValidationError(item.get("id", "<missing id>"), problem)
                                for problem in official_problems(item, directory.parent)]
            errors.extend(item_errors)
            question_id = item.get("id")
            if question_id in seen_ids:
                errors.append(ValidationError(str(question_id), f"duplicate id (in {path.name})"))
            seen_ids.add(question_id)
            if not item_errors:
                questions.append(item)
    return questions, errors
