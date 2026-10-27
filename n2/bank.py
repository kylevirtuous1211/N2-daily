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
}

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

TEXT_FIELDS = ("question", "passage", "full_sentence")


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
    if len(choices) != 4 or not all(isinstance(choice, str) and choice.strip() for choice in choices):
        problems.append("need exactly 4 non-empty choices")
    elif len({strip_markup(choice) for choice in choices}) != 4:
        problems.append("choices must be distinct")
    if not 0 <= question["answer"] <= 3:
        problems.append("answer must be 0-3")
    if len(question["choice_notes"]) != 4:
        problems.append("need exactly 4 choice_notes")

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
    if section == "reading":
        if not isinstance(question.get("passage"), str) or len(strip_markup(question["passage"])) < 80:
            problems.append("reading needs a passage of at least 80 characters")
        if not isinstance(question.get("passage_translation"), str):
            problems.append("reading needs passage_translation")
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


class QuestionBank:
    def __init__(self, questions: list[dict]):
        self.questions = questions
        self.by_id = {question["id"]: question for question in questions}
        self.by_section: dict[str, list[dict]] = {section: [] for section in SECTIONS}
        for question in questions:
            self.by_section[question["section"]].append(question)

    @classmethod
    def load(cls, directory: Path) -> "QuestionBank":
        questions, errors = load_and_validate(directory)
        if errors:
            details = "\n".join(str(error) for error in errors[:20])
            raise ValueError(f"{len(errors)} problems in question bank:\n{details}")
        return cls(questions)


def load_and_validate(directory: Path) -> tuple[list[dict], list[ValidationError]]:
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
            errors.extend(item_errors)
            question_id = item.get("id")
            if question_id in seen_ids:
                errors.append(ValidationError(str(question_id), f"duplicate id (in {path.name})"))
            seen_ids.add(question_id)
            if not item_errors:
                questions.append(item)
    return questions, errors
