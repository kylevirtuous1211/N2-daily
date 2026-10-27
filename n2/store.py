"""SQLite persistence: mini tests, attempts, and the vocab/grammar deck."""

from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import fsrs
from .bank import OFFICIAL_PARTS, SECTIONS, QuestionBank

TEST_PLANS = {
    10: {"kanji_reading": 2, "orthography": 1, "context": 2, "paraphrase": 1,
         "grammar_form": 2, "sentence_order": 1, "reading": 1},
    20: {"kanji_reading": 3, "orthography": 2, "word_formation": 1, "context": 3, "paraphrase": 2,
         "usage": 1, "grammar_form": 4, "sentence_order": 2, "reading": 2},
    30: {"kanji_reading": 4, "orthography": 3, "word_formation": 2, "context": 4, "paraphrase": 3,
         "usage": 2, "grammar_form": 6, "sentence_order": 3, "reading": 3},
}
RETEST_AFTER = timedelta(days=2)
LEARN_AHEAD = timedelta(minutes=20)
DEFAULT_SETTINGS = {"new_cards_per_day": 20, "desired_retention": 0.9, "test_furigana": False}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    size INTEGER NOT NULL,
    submitted_at TEXT,
    score INTEGER,
    seconds REAL
);
CREATE TABLE IF NOT EXISTS test_questions (
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    choice_order TEXT NOT NULL,
    chosen INTEGER,
    correct INTEGER,
    PRIMARY KEY (test_id, position)
);
CREATE INDEX IF NOT EXISTS idx_test_questions_question ON test_questions(question_id);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('vocab', 'grammar')),
    key TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    source_question TEXT,
    added_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'new',
    stability REAL NOT NULL DEFAULT 0,
    difficulty REAL NOT NULL DEFAULT 0,
    due TEXT,
    last_review TEXT,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    state_before TEXT NOT NULL,
    stability_after REAL NOT NULL,
    difficulty_after REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_text(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def from_text(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def local_date(moment: datetime) -> str:
    return moment.astimezone().date().isoformat()


OFFICIAL_SET_NAMES = {"2012": "公式問題集（2012）", "2018": "公式問題集 第二集（2018）"}


def test_label(test) -> str:
    if test["kind"] != "official":
        return f"Mini test · {test['size']} questions"
    set_name = OFFICIAL_SET_NAMES.get(test["official_set"], test["official_set"])
    return f"{set_name} {OFFICIAL_PARTS[test['official_part']]['ja']}"


def card_key(kind: str, data: dict) -> str:
    if kind == "vocab":
        return f"vocab:{data['word']}:{data['reading']}"
    return f"grammar:{data['pattern']}"


class Store:
    def __init__(self, db_path: Path, bank: QuestionBank, clock=utc_now, rng: random.Random | None = None):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bank = bank
        self.clock = clock
        self.rng = rng or random.Random()
        self.lock = threading.Lock()
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring databases created by older versions up to the current schema."""
        test_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(tests)")}
        with self.connection:
            if "kind" not in test_columns:
                self.connection.execute("ALTER TABLE tests ADD COLUMN kind TEXT NOT NULL DEFAULT 'daily'")
            if "official_set" not in test_columns:
                self.connection.execute("ALTER TABLE tests ADD COLUMN official_set TEXT")
            if "official_part" not in test_columns:
                self.connection.execute("ALTER TABLE tests ADD COLUMN official_part TEXT")

    def close(self) -> None:
        self.connection.close()

    # --- settings -------------------------------------------------------

    def settings(self) -> dict:
        stored = {row["key"]: json.loads(row["value"]) for row in self.connection.execute("SELECT * FROM settings")}
        return {**DEFAULT_SETTINGS, **stored}

    def update_settings(self, changes: dict) -> dict:
        unknown = set(changes) - set(DEFAULT_SETTINGS)
        if unknown:
            raise BadRequest(f"unknown settings: {sorted(unknown)}")
        retention = changes.get("desired_retention")
        if retention is not None and not 0.7 <= float(retention) <= 0.97:
            raise BadRequest("desired_retention must be between 0.70 and 0.97")
        new_per_day = changes.get("new_cards_per_day")
        if new_per_day is not None and not 0 <= int(new_per_day) <= 200:
            raise BadRequest("new_cards_per_day must be between 0 and 200")
        with self.lock, self.connection:
            for key, value in changes.items():
                self.connection.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
        return self.settings()

    def scheduler(self) -> fsrs.Scheduler:
        return fsrs.Scheduler(desired_retention=float(self.settings()["desired_retention"]))

    # --- tests ----------------------------------------------------------

    def create_test(self, size: int) -> dict:
        if size not in TEST_PLANS:
            raise BadRequest(f"size must be one of {sorted(TEST_PLANS)}")
        now = self.clock()
        history = self._question_history()
        chosen: list[dict] = []
        for section, quota in TEST_PLANS[size].items():
            chosen.extend(self._pick_questions(section, quota, history, now))

        return self._insert_test(chosen, now, shuffle=True)

    def create_official_test(self, official_set: str, part: str) -> dict:
        questions = self.bank.official_sets.get(official_set, {}).get(part)
        if not questions:
            raise BadRequest(f"no official test {official_set!r} / {part!r}")
        return self._insert_test(questions, self.clock(), shuffle=False, official=(official_set, part))

    def _insert_test(self, questions: list[dict], now: datetime, shuffle: bool,
                     official: tuple[str, str] | None = None) -> dict:
        kind = "official" if official else "daily"
        official_set, official_part = official or (None, None)
        with self.lock, self.connection:
            cursor = self.connection.execute(
                """INSERT INTO tests(created_at, local_date, size, kind, official_set, official_part)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (to_text(now), local_date(now), len(questions), kind, official_set, official_part),
            )
            test_id = cursor.lastrowid
            for position, question in enumerate(questions):
                order = list(range(len(question["choices"])))
                if shuffle and question["section"] != "sentence_order":
                    self.rng.shuffle(order)
                self.connection.execute(
                    "INSERT INTO test_questions(test_id, position, question_id, choice_order) VALUES (?, ?, ?, ?)",
                    (test_id, position, question["id"], json.dumps(order)),
                )
        return self.get_test(test_id)

    def _question_history(self) -> dict[str, dict]:
        rows = self.connection.execute(
            """
            SELECT tq.question_id, tq.correct, t.submitted_at
            FROM test_questions tq JOIN tests t ON t.id = tq.test_id
            WHERE t.submitted_at IS NOT NULL
            ORDER BY t.submitted_at
            """
        )
        history: dict[str, dict] = {}
        for row in rows:
            history[row["question_id"]] = {"last_seen": from_text(row["submitted_at"]), "last_correct": bool(row["correct"])}
        return history

    def _pick_questions(self, section: str, quota: int, history: dict, now: datetime) -> list[dict]:
        pool = list(self.bank.by_section[section])
        self.rng.shuffle(pool)
        retest = [q for q in pool if q["id"] in history and not history[q["id"]]["last_correct"]
                  and now - history[q["id"]]["last_seen"] >= RETEST_AFTER]
        unseen = [q for q in pool if q["id"] not in history]
        seen = sorted((q for q in pool if q["id"] in history and q not in retest),
                      key=lambda q: history[q["id"]]["last_seen"])
        retest_quota = math.ceil(quota / 3)
        ordered = retest[:retest_quota] + unseen + retest[retest_quota:] + seen
        return ordered[:quota]

    def get_test(self, test_id: int) -> dict:
        test = self.connection.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        if test is None:
            raise NotFound(f"test {test_id} not found")
        rows = self.connection.execute(
            "SELECT * FROM test_questions WHERE test_id = ? ORDER BY position", (test_id,)
        ).fetchall()
        submitted = test["submitted_at"] is not None
        items = []
        for row in rows:
            question = self.bank.by_id.get(row["question_id"])
            if question is None:
                continue
            order = json.loads(row["choice_order"])
            item = {
                "position": row["position"],
                "question_id": question["id"],
                "section": question["section"],
                "question": question["question"],
                "passage": question.get("passage"),
                "passage_group": question.get("passage_group"),
                "passage_image": question.get("passage_image"),
                "question_image": question.get("question_image"),
                "audio": question.get("audio"),
                "choices_hidden": bool(question.get("choices_hidden")),
                "official": question.get("official"),
                "choices": [question["choices"][index] for index in order],
            }
            if question.get("choices_hidden") and not submitted:
                item["choices"] = [str(number) for number in range(1, len(order) + 1)]
            if question["section"] == "sentence_order":
                item["star"] = question["star"]
            if submitted:
                item.update(self._review_fields(question, order))
                item["chosen"] = row["chosen"]
                item["correct"] = bool(row["correct"])
            items.append(item)
        return {
            "id": test["id"],
            "kind": test["kind"],
            "label": test_label(test),
            "minutes": OFFICIAL_PARTS[test["official_part"]]["minutes"] if test["official_part"] else None,
            "created_at": test["created_at"],
            "local_date": test["local_date"],
            "size": test["size"],
            "submitted": submitted,
            "submitted_at": test["submitted_at"],
            "score": test["score"],
            "seconds": test["seconds"],
            "questions": items,
            "sections": SECTIONS,
        }

    @staticmethod
    def _review_fields(question: dict, order: list[int]) -> dict:
        fields = {
            "answer": order.index(question["answer"]),
            "choice_notes": [question["choice_notes"][index] for index in order],
            "translation": question["translation"],
            "explanation": question["explanation"],
            "full_sentence": question.get("full_sentence"),
            "passage_translation": question.get("passage_translation"),
            "script": question.get("script"),
            "script_translation": question.get("script_translation"),
            "vocab": question["vocab"],
            "grammar": question.get("grammar", []),
        }
        if question["section"] == "sentence_order":
            fields["correct_order"] = [order.index(index) for index in question["correct_order"]]
        return fields

    def submit_test(self, test_id: int, answers: dict, seconds: float | None) -> dict:
        test = self.connection.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
        if test is None:
            raise NotFound(f"test {test_id} not found")
        if test["submitted_at"] is not None:
            raise BadRequest("test already submitted")
        rows = self.connection.execute("SELECT * FROM test_questions WHERE test_id = ?", (test_id,)).fetchall()
        now = self.clock()
        score = 0
        with self.lock, self.connection:
            for row in rows:
                question = self.bank.by_id[row["question_id"]]
                order = json.loads(row["choice_order"])
                chosen = answers.get(str(row["position"]))
                if chosen is not None and chosen not in range(len(order)):
                    raise BadRequest(f"invalid choice for question {row['position']}")
                correct = chosen is not None and order[chosen] == question["answer"]
                score += correct
                self.connection.execute(
                    "UPDATE test_questions SET chosen = ?, correct = ? WHERE test_id = ? AND position = ?",
                    (chosen, int(correct), test_id, row["position"]),
                )
            self.connection.execute(
                "UPDATE tests SET submitted_at = ?, score = ?, seconds = ? WHERE id = ?",
                (to_text(now), score, seconds, test_id),
            )
        return self.get_test(test_id)

    def delete_test(self, test_id: int) -> None:
        with self.lock, self.connection:
            cursor = self.connection.execute("DELETE FROM tests WHERE id = ? AND submitted_at IS NULL", (test_id,))
        if cursor.rowcount == 0:
            raise NotFound(f"no unfinished test {test_id}")

    def list_tests(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM tests ORDER BY id DESC")
        return [{**dict(row), "label": test_label(row)} for row in rows]

    def official_catalog(self) -> list[dict]:
        """Every official test part with its attempts, newest first."""
        tests = [test for test in self.list_tests() if test["kind"] == "official"]
        catalog = []
        for official_set in sorted(self.bank.official_sets):
            for part, questions in self.bank.official_sets[official_set].items():
                attempts = [test for test in tests if test["official_set"] == official_set and test["official_part"] == part]
                catalog.append({
                    "set": official_set,
                    "part": part,
                    "set_name": OFFICIAL_SET_NAMES.get(official_set, official_set),
                    "part_name": OFFICIAL_PARTS[part]["ja"],
                    "minutes": OFFICIAL_PARTS[part]["minutes"],
                    "count": len(questions),
                    "attempts": [test for test in attempts if test["submitted_at"]],
                    "unfinished": next((test["id"] for test in attempts if not test["submitted_at"]), None),
                })
        return catalog

    def section_stats(self) -> dict:
        rows = self.connection.execute(
            """
            SELECT tq.question_id, tq.correct FROM test_questions tq
            JOIN tests t ON t.id = tq.test_id WHERE t.submitted_at IS NOT NULL
            """
        )
        stats = {section: {"answered": 0, "correct": 0} for section in SECTIONS}
        for row in rows:
            question = self.bank.by_id.get(row["question_id"])
            if question is None:
                continue
            stats[question["section"]]["answered"] += 1
            stats[question["section"]]["correct"] += row["correct"]
        return stats

    # --- deck -----------------------------------------------------------

    def add_card(self, kind: str, data: dict, source_question: str | None) -> dict:
        if kind not in ("vocab", "grammar"):
            raise BadRequest("kind must be vocab or grammar")
        required = ("word", "reading", "meaning") if kind == "vocab" else ("pattern", "meaning")
        if not all(isinstance(data.get(field), str) and data[field] for field in required):
            raise BadRequest(f"{kind} card needs {', '.join(required)}")
        key = card_key(kind, data)
        with self.lock, self.connection:
            self.connection.execute(
                """INSERT INTO cards(kind, key, data, source_question, added_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO NOTHING""",
                (kind, key, json.dumps(data, ensure_ascii=False), source_question, to_text(self.clock())),
            )
        row = self.connection.execute("SELECT * FROM cards WHERE key = ?", (key,)).fetchone()
        return self._card_view(row, self.clock())

    def card_keys(self) -> list[str]:
        return [row["key"] for row in self.connection.execute("SELECT key FROM cards")]

    def delete_card(self, card_id: int) -> None:
        with self.lock, self.connection:
            cursor = self.connection.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        if cursor.rowcount == 0:
            raise NotFound(f"card {card_id} not found")

    def list_cards(self) -> list[dict]:
        now = self.clock()
        rows = self.connection.execute("SELECT * FROM cards ORDER BY added_at DESC, id DESC")
        return [self._card_view(row, now) for row in rows]

    def _card_view(self, row: sqlite3.Row, now: datetime) -> dict:
        state = _card_state(row)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "key": row["key"],
            "data": json.loads(row["data"]),
            "source_question": row["source_question"],
            "added_at": row["added_at"],
            "state": row["state"],
            "stability": row["stability"],
            "difficulty": row["difficulty"],
            "due": row["due"],
            "last_review": row["last_review"],
            "reps": row["reps"],
            "lapses": row["lapses"],
            "retrievability": fsrs.current_retrievability(state, now),
        }

    def study_queue(self) -> dict:
        """Due cards (most-forgotten first), learning cards, then today's new cards."""
        now = self.clock()
        scheduler = self.scheduler()
        rows = self.connection.execute("SELECT * FROM cards WHERE state != 'new'").fetchall()
        due_rows = [row for row in rows if from_text(row["due"]) <= now + LEARN_AHEAD]
        due_rows.sort(key=lambda row: (
            row["state"] in (fsrs.LEARNING, fsrs.RELEARNING),
            fsrs.current_retrievability(_card_state(row), now) or 0,
        ))

        new_limit = int(self.settings()["new_cards_per_day"])
        introduced_today = self.connection.execute(
            "SELECT COUNT(*) FROM review_log WHERE state_before = 'new' AND local_date = ?", (local_date(now),)
        ).fetchone()[0]
        new_rows = self.connection.execute(
            "SELECT * FROM cards WHERE state = 'new' ORDER BY added_at, id LIMIT ?",
            (max(new_limit - introduced_today, 0),),
        ).fetchall()

        cards = [self._study_view(row, now, scheduler) for row in due_rows + new_rows]
        total_new = self.connection.execute("SELECT COUNT(*) FROM cards WHERE state = 'new'").fetchone()[0]
        return {"cards": cards, "new_remaining_today": len(new_rows), "new_total": total_new}

    def _study_view(self, row: sqlite3.Row, now: datetime, scheduler: fsrs.Scheduler) -> dict:
        view = self._card_view(row, now)
        previews = scheduler.preview(_card_state(row), now)
        view["intervals"] = {str(rating): (state.due - now).total_seconds() for rating, state in previews.items()}
        return view

    def review_card(self, card_id: int, rating: int) -> dict:
        if rating not in fsrs.RATINGS:
            raise BadRequest("rating must be 1-4")
        now = self.clock()
        scheduler = self.scheduler()
        with self.lock, self.connection:
            row = self.connection.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                raise NotFound(f"card {card_id} not found")
            updated = scheduler.review(_card_state(row), rating, now)
            self.connection.execute(
                """UPDATE cards SET state = ?, stability = ?, difficulty = ?, due = ?, last_review = ?,
                   reps = ?, lapses = ? WHERE id = ?""",
                (updated.state, updated.stability, updated.difficulty, to_text(updated.due),
                 to_text(updated.last_review), updated.reps, updated.lapses, card_id),
            )
            self.connection.execute(
                """INSERT INTO review_log(card_id, rating, reviewed_at, local_date, state_before,
                   stability_after, difficulty_after) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (card_id, rating, to_text(now), local_date(now), row["state"], updated.stability, updated.difficulty),
            )
            fresh = self.connection.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return self._study_view(fresh, now, scheduler)

    # --- dashboard ------------------------------------------------------

    def summary(self) -> dict:
        now = self.clock()
        today = local_date(now)
        tests = self.list_tests()
        submitted_dates = {test["local_date"] for test in tests if test["submitted_at"]}
        streak = 0
        day = now.astimezone().date()
        if today not in submitted_dates:
            day -= timedelta(days=1)
        while day.isoformat() in submitted_dates:
            streak += 1
            day -= timedelta(days=1)
        queue = self.study_queue()
        due_now = sum(1 for card in queue["cards"] if card["state"] != "new" and from_text(card["due"]) <= now)
        reviewed_today = self.connection.execute(
            "SELECT COUNT(*) FROM review_log WHERE local_date = ?", (today,)
        ).fetchone()[0]
        return {
            "today": today,
            "today_tests": [test for test in tests if test["local_date"] == today],
            "unfinished_test": next((test for test in tests if not test["submitted_at"] and test["kind"] == "daily"), None),
            "streak": streak,
            "deck_size": self.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
            "due_now": due_now,
            "new_available": queue["new_remaining_today"],
            "reviewed_today": reviewed_today,
            "bank_size": len(self.bank.questions),
            "seen_questions": len({question["id"] for question in self.bank.questions} & set(self._question_history())),
            "recent_tests": [test for test in tests if test["submitted_at"]][:14],
            "official": self.official_catalog(),
            "section_stats": self.section_stats(),
            "sections": SECTIONS,
        }


def _card_state(row: sqlite3.Row) -> fsrs.CardState:
    return fsrs.CardState(
        state=row["state"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due=from_text(row["due"]),
        last_review=from_text(row["last_review"]),
        reps=row["reps"],
        lapses=row["lapses"],
    )
