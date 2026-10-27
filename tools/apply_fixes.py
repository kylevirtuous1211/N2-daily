"""Apply reviewed content fixes. Usage: python tools/apply_fixes.py fixes.json [--dry-run]

fixes.json is a list of {"id": "kr-001", "ops": [{"path": "vocab[2].reading", "value": ...}, ...]}.
A path of "" replaces the whole question. Paths use dots for keys and [n] for list items.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "content" / "questions"
TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def parse_path(path: str) -> list[str | int]:
    steps: list[str | int] = []
    for key, index in TOKEN.findall(path):
        steps.append(int(index) if index else key)
    return steps


def set_path(question: dict, path: str, value) -> None:
    steps = parse_path(path)
    target = question
    for step in steps[:-1]:
        target = target[step]
    last = steps[-1]
    if isinstance(last, int) and last == len(target):
        target.append(value)
    else:
        target[last] = value


def main(argv: list[str]) -> int:
    fixes = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    dry_run = "--dry-run" in argv
    files = {path: json.loads(path.read_text(encoding="utf-8")) for path in sorted(QUESTIONS_DIR.glob("*.json"))}
    index = {question["id"]: (path, position) for path, items in files.items() for position, question in enumerate(items)}

    touched_paths: dict[tuple[str, str], int] = {}
    applied = 0
    for fix_number, fix in enumerate(fixes):
        if fix["id"] not in index:
            print(f"SKIP unknown id {fix['id']}")
            continue
        path, position = index[fix["id"]]
        for op in fix["ops"]:
            key = (fix["id"], op["path"])
            if key in touched_paths and touched_paths[key] != fix_number:
                print(f"CONFLICT {fix['id']} {op['path']} (fix {touched_paths[key]} vs {fix_number}) - later fix wins")
            touched_paths[key] = fix_number
            if op["path"] == "":
                files[path][position] = {**op["value"], "id": fix["id"]}
            else:
                set_path(files[path][position], op["path"], op["value"])
            applied += 1

    print(f"{applied} operations from {len(fixes)} fixes")
    if dry_run:
        return 0
    for path, items in files.items():
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
