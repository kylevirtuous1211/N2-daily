"""Run the N2 Daily server. Usage: python serve.py [--port 8765] [--db path] [--idle-timeout seconds]"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from n2.bank import QuestionBank
from n2.server import AppServer
from n2.store import Store

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("LOCALAPPDATA", APP_DIR)) / "N2Daily" / "n2daily.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--idle-timeout", type=float, default=None,
                        help="exit after this many seconds without requests")
    args = parser.parse_args()

    bank = QuestionBank.load(APP_DIR / "content" / "questions")
    store = Store(args.db, bank)
    server = AppServer(("127.0.0.1", args.port), store, idle_timeout=args.idle_timeout)
    print(f"N2 Daily: http://127.0.0.1:{args.port}/  ({len(bank.questions)} questions, db {args.db})", flush=True)
    try:
        server.serve_forever()
    finally:
        store.close()


if __name__ == "__main__":
    main()
