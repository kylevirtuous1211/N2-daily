"""Validate the question bank. Usage: python tools/validate_content.py [file.json ...]"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from n2.bank import SECTIONS, load_and_validate, validate_question  # noqa: E402

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "content" / "questions"


def main(paths: list[str]) -> int:
    if paths:
        errors = []
        count = 0
        for path in paths:
            for item in json.loads(Path(path).read_text(encoding="utf-8")):
                count += 1
                errors.extend(validate_question(item))
        questions_ok = count - len({error.question_id for error in errors})
    else:
        questions, errors = load_and_validate(QUESTIONS_DIR)
        questions_ok = len(questions)
        counts = Counter(question["section"] for question in questions)
        for section in SECTIONS:
            print(f"{section:16} {counts.get(section, 0):4}")

    for error in errors:
        print(f"ERROR {error}")
    print(f"{questions_ok} valid questions, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
