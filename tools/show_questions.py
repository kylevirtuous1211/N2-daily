"""Print questions by id as JSON. Usage: python tools/show_questions.py kr-001 kr-002 ..."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "content" / "questions"


def main(ids: list[str]) -> int:
    wanted = set(ids)
    found = []
    for path in sorted(QUESTIONS_DIR.glob("*.json")):
        for question in json.loads(path.read_text(encoding="utf-8")):
            if question.get("id") in wanted:
                found.append({"file": path.name, **question})
    missing = wanted - {question["id"] for question in found}
    print(json.dumps(found, ensure_ascii=False, indent=1))
    if missing:
        print(f"MISSING: {sorted(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
