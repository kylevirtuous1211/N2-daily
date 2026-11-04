"""Validate question banks.

Usage:
    python tools/validate_content.py                 # main bank + official bank (if present)
    python tools/validate_content.py FILE.json ...   # single files; files under content/official are
                                                     # checked as official questions (audio not required yet)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from n2.bank import SECTIONS, load_and_validate, official_problems, validate_question  # noqa: E402
from n2.topics import TOPICS_FILE, Topics, coverage_problems  # noqa: E402

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
QUESTIONS_DIR = CONTENT_DIR / "questions"
OFFICIAL_DIR = CONTENT_DIR / "official"


def validate_files(paths: list[str]) -> tuple[int, list]:
    errors, count = [], 0
    for name in paths:
        path = Path(name).resolve()
        is_official = OFFICIAL_DIR.resolve() in path.parents
        for item in json.loads(path.read_text(encoding="utf-8")):
            count += 1
            errors.extend(validate_question(item))
            if is_official:
                from n2.bank import ValidationError
                errors.extend(ValidationError(item.get("id", "?"), problem)
                              for problem in official_problems(item, OFFICIAL_DIR, require_audio=False))
    return count - len({error.question_id for error in errors}), errors


def topic_label_problems(questions: list[dict], official: list[dict] | None) -> list[str]:
    """Each bank has its own label file: content/topics.json (public) and content/official/topics.json (local)."""
    topics = Topics.load(TOPICS_FILE)
    problems = coverage_problems(topics, questions, topics.words)
    if official is not None:
        official_file = OFFICIAL_DIR / "topics.json"
        labels = json.loads(official_file.read_text(encoding="utf-8"))["words"] if official_file.is_file() else {}
        public_words = set(topics.words)
        official_only = [{**question, "vocab": [entry for entry in question.get("vocab", [])
                                               if f"{entry['word']}:{entry['reading']}" not in public_words]}
                         for question in official]
        problems += [f"official {problem}" for problem in coverage_problems(topics, official_only, labels)]
    return problems


def main(paths: list[str]) -> int:
    if paths:
        valid, errors = validate_files(paths)
    else:
        questions, errors = load_and_validate(QUESTIONS_DIR)
        valid = len(questions)
        counts = Counter(question["section"] for question in questions)
        for section in SECTIONS:
            if counts.get(section):
                print(f"{section:20} {counts[section]:4}")
        official_questions = OFFICIAL_DIR / "questions"
        if official_questions.is_dir():
            official, official_errors = load_and_validate(official_questions, official=True)
            errors += official_errors
            print(f"official questions  {len(official):4}")
            valid += len(official)
        errors += [f"topics: {problem}" for problem in
                   topic_label_problems(questions, official if official_questions.is_dir() else None)]

    for error in errors:
        print(f"ERROR {error}")
    print(f"{valid} valid questions, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
