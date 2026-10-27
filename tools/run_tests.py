"""Run every check: content validation, Python tests (unit + end-to-end), JS tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

CHECKS = [
    ("content", [sys.executable, "tools/validate_content.py"]),
    ("python tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
    ("js tests", ["node", "--test", *sorted(str(path.relative_to(APP_DIR)) for path in (APP_DIR / "tests").glob("*.test.mjs"))]),
]
if any((APP_DIR / "cache").glob("jmdict-eng-*.json")):
    CHECKS.append(("readings vs JMdict", [sys.executable, "tools/check_readings.py", "--fail-on-findings"]))


def main() -> int:
    failed = []
    for name, command in CHECKS:
        print(f"== {name}", flush=True)
        if subprocess.run(command, cwd=APP_DIR).returncode != 0:
            failed.append(name)
    print("== FAILED: " + ", ".join(failed) if failed else "== all checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
