"""End-to-end: real HTTP server + real SQLite + shipped question bank, driven over HTTP.

Only the clock is controllable, so we can travel through days of study.
"""

import json
import random
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from n2.bank import QuestionBank, strip_markup
from n2.server import AppServer
from n2.store import TEST_PLANS, Store

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "content" / "questions"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class AppHarness:
    def __init__(self, official_dir: Path | None = None):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.bank = QuestionBank.load(QUESTIONS_DIR, official_dir / "questions" if official_dir else None)
        self.store = Store(Path(self.directory.name) / "test.sqlite3", self.bank, clock=self.clock, rng=random.Random(7))
        server_options = {"official_dir": official_dir} if official_dir else {}
        self.server = AppServer(("127.0.0.1", 0), self.store, **server_options)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.directory.cleanup()

    def request(self, method, path, body=None, expect=200):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(request) as response:
                status, payload = response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                status, payload = error.code, error.read()
        if status != expect:
            raise AssertionError(f"{method} {path} -> {status}: {payload[:300]!r}")
        return json.loads(payload) if path.startswith("/api/") else payload


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.app = AppHarness()

    def tearDown(self):
        self.app.close()

    def take_test(self, size=20, pick=lambda question: 0):
        test = self.app.request("POST", "/api/tests", {"size": size})
        answers = {str(question["position"]): pick(question) for question in test["questions"]}
        return test, self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": answers, "seconds": 600})

    def test_serves_app_and_health(self):
        self.assertEqual(self.app.request("GET", "/api/health")["app"], "n2-daily")
        html = self.app.request("GET", "/")
        self.assertIn(b"<title>N2 Daily</title>", html)
        self.assertIn(b"renderJa", self.app.request("GET", "/markup.js"))
        self.app.request("GET", "/api/nope", expect=404)
        self.app.request("POST", "/api/tests", {"size": 7}, expect=400)
        self.app.request("GET", "/../serve.py")  # path traversal falls back to index.html

    def test_daily_test_follows_plan_and_hides_answers_until_submitted(self):
        test = self.app.request("POST", "/api/tests", {"size": 20})
        self.assertEqual(len(test["questions"]), 20)
        sections = [question["section"] for question in test["questions"]]
        for section, quota in TEST_PLANS[20].items():
            self.assertEqual(sections.count(section), quota, section)
        for question in test["questions"]:
            for hidden in ("answer", "explanation", "choice_notes", "vocab", "translation"):
                self.assertNotIn(hidden, question)
        summary = self.app.request("GET", "/api/summary")
        self.assertEqual(summary["unfinished_test"]["id"], test["id"])

    def test_review_maps_shuffled_choices_back_to_the_bank(self):
        test, review = self.take_test(pick=lambda question: question["position"] % 4)
        self.assertTrue(review["submitted"])
        score = 0
        for item in review["questions"]:
            source = self.app.bank.by_id[item["question_id"]]
            correct_text = source["choices"][source["answer"]]
            self.assertEqual(item["choices"][item["answer"]], correct_text)
            self.assertEqual(item["choice_notes"][item["answer"]], source["choice_notes"][source["answer"]])
            self.assertEqual(item["correct"], item["chosen"] == item["answer"])
            self.assertTrue(item["vocab"])
            self.assertTrue(item["explanation"])
            if item["section"] == "sentence_order":
                built = "".join(strip_markup(item["choices"][index]) for index in item["correct_order"])
                self.assertIn(built.replace(" ", ""), strip_markup(item["full_sentence"]).replace(" ", ""))
            score += item["correct"]
        self.assertEqual(review["score"], score)
        self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {}}, expect=400)

    def test_unanswered_questions_count_as_wrong(self):
        test = self.app.request("POST", "/api/tests", {"size": 10})
        review = self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {}, "seconds": 5})
        self.assertEqual(review["score"], 0)
        self.assertTrue(all(item["chosen"] is None for item in review["questions"]))

    def test_next_tests_prefer_unseen_then_bring_back_mistakes(self):
        first, first_review = self.take_test(pick=lambda question: None)  # everything wrong
        first_ids = {item["question_id"] for item in first_review["questions"]}

        self.app.clock.advance(hours=20)
        second, _ = self.take_test(pick=lambda question: 0)
        self.assertFalse(first_ids & {item["question_id"] for item in second["questions"]},
                         "next-day test should use unseen questions before the 2-day retest window")

        self.app.clock.advance(days=3)
        third = self.app.request("POST", "/api/tests", {"size": 20})
        retested = first_ids & {item["question_id"] for item in third["questions"]}
        self.assertTrue(retested, "mistakes should come back after the retest window")
        self.assertLessEqual(len(retested), 10, "at most a third of each section is retests")

    def test_streak_counts_consecutive_days(self):
        self.take_test(size=10)
        self.assertEqual(self.app.request("GET", "/api/summary")["streak"], 1)
        self.app.clock.advance(days=1)
        self.assertEqual(self.app.request("GET", "/api/summary")["streak"], 1, "streak survives until the day ends")
        self.take_test(size=10)
        self.assertEqual(self.app.request("GET", "/api/summary")["streak"], 2)
        self.app.clock.advance(days=2)
        self.assertEqual(self.app.request("GET", "/api/summary")["streak"], 0)

    def test_deck_and_spaced_repetition_flow(self):
        _, review = self.take_test(size=10)
        vocab = review["questions"][0]["vocab"][0]
        grammar_entry = next(entry for item in review["questions"] for entry in item["grammar"])

        card = self.app.request("POST", "/api/cards", {"kind": "vocab", "data": vocab, "source_question": "x"})
        again = self.app.request("POST", "/api/cards", {"kind": "vocab", "data": vocab, "source_question": "x"})
        self.assertEqual(card["id"], again["id"], "adding the same word twice is idempotent")
        self.app.request("POST", "/api/cards", {"kind": "grammar", "data": grammar_entry})
        self.app.request("POST", "/api/cards", {"kind": "vocab", "data": {"word": "x"}}, expect=400)
        self.assertIn(f"vocab:{vocab['word']}:{vocab['reading']}", self.app.request("GET", "/api/cards/keys"))

        queue = self.app.request("GET", "/api/study")
        self.assertEqual({entry["state"] for entry in queue["cards"]}, {"new"})
        self.assertEqual(len(queue["cards"]), 2)
        self.assertEqual(set(queue["cards"][0]["intervals"]), {"1", "2", "3", "4"})

        learning = self.app.request("POST", f"/api/cards/{card['id']}/review", {"rating": 3})
        self.assertEqual(learning["state"], "learning")
        self.app.clock.advance(minutes=11)
        due_ids = [entry["id"] for entry in self.app.request("GET", "/api/study")["cards"]]
        self.assertIn(card["id"], due_ids)

        graduated = self.app.request("POST", f"/api/cards/{card['id']}/review", {"rating": 3})
        self.assertEqual(graduated["state"], "review")
        self.assertNotIn(card["id"], [entry["id"] for entry in self.app.request("GET", "/api/study")["cards"]])

        self.app.clock.now = datetime.fromisoformat(graduated["due"]) + timedelta(days=2)
        summary = self.app.request("GET", "/api/summary")
        self.assertEqual(summary["due_now"], 1)
        listed = next(entry for entry in self.app.request("GET", "/api/cards") if entry["id"] == card["id"])
        self.assertLess(listed["retrievability"], 0.9, "overdue card should be below target recall")

        self.app.request("POST", f"/api/cards/{card['id']}/review", {"rating": 9}, expect=400)
        self.app.request("DELETE", f"/api/cards/{card['id']}")
        self.app.request("DELETE", f"/api/cards/{card['id']}", expect=404)

    def test_review_queue_puts_most_forgotten_first(self):
        _, review = self.take_test(size=10)
        entries = [entry for item in review["questions"] for entry in item["vocab"]][:3]
        ids = [self.app.request("POST", "/api/cards", {"kind": "vocab", "data": entry})["id"] for entry in entries]
        # Card 0: Easy (long interval). Cards 1 and 2: learned via Good/Good (short interval).
        self.app.request("POST", f"/api/cards/{ids[0]}/review", {"rating": 4})
        for card_id in ids[1:]:
            self.app.request("POST", f"/api/cards/{card_id}/review", {"rating": 3})
        self.app.clock.advance(minutes=15)
        for card_id in ids[1:]:
            self.app.request("POST", f"/api/cards/{card_id}/review", {"rating": 3})
        self.app.clock.advance(days=60)
        queue = [entry for entry in self.app.request("GET", "/api/study")["cards"] if entry["state"] == "review"]
        recalls = [entry["retrievability"] for entry in queue]
        self.assertEqual(recalls, sorted(recalls))
        self.assertEqual(queue[-1]["id"], ids[0], "the strongest memory comes last")

    def test_new_card_daily_limit(self):
        self.app.request("PATCH", "/api/settings", {"new_cards_per_day": 2})
        _, review = self.take_test(size=10)
        entries = [entry for item in review["questions"] for entry in item["vocab"]][:4]
        for entry in entries:
            self.app.request("POST", "/api/cards", {"kind": "vocab", "data": entry})
        queue = self.app.request("GET", "/api/study")["cards"]
        self.assertEqual(len(queue), 2)
        for entry in queue:
            self.app.request("POST", f"/api/cards/{entry['id']}/review", {"rating": 4})
        self.assertEqual(self.app.request("GET", "/api/study")["cards"], [])
        self.app.clock.advance(days=1)
        self.assertEqual(len(self.app.request("GET", "/api/study")["cards"]), 2)
        self.app.request("PATCH", "/api/settings", {"desired_retention": 2}, expect=400)

    def test_discard_unfinished_test(self):
        test = self.app.request("POST", "/api/tests", {"size": 10})
        self.app.request("DELETE", f"/api/tests/{test['id']}")
        self.app.request("GET", f"/api/tests/{test['id']}", expect=404)
        self.assertIsNone(self.app.request("GET", "/api/summary")["unfinished_test"])


if __name__ == "__main__":
    unittest.main()


FIXTURE_OFFICIAL = Path(__file__).resolve().parent / "fixtures" / "official"


class OfficialTestFlowTest(unittest.TestCase):
    """Official practice tests: fixed order, no shuffling, hidden listening choices, audio with Range."""

    def setUp(self):
        self.app = AppHarness(official_dir=FIXTURE_OFFICIAL)

    def tearDown(self):
        self.app.close()

    def fetch(self, path, headers=None):
        request = urllib.request.Request(self.app.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers), error.read()

    def test_catalog_lists_parts_with_time_limits(self):
        catalog = {(entry["set"], entry["part"]): entry for entry in self.app.request("GET", "/api/official")}
        self.assertEqual(catalog[("fx", "language")]["count"], 2)
        self.assertEqual(catalog[("fx", "language")]["minutes"], 105)
        self.assertEqual(catalog[("fx", "listening")]["minutes"], 50)
        self.assertEqual(self.app.request("GET", "/api/summary")["official"], self.app.request("GET", "/api/official"))

    def test_language_test_keeps_booklet_order_and_choice_order(self):
        test = self.app.request("POST", "/api/tests", {"official_set": "fx", "official_part": "language"})
        self.assertEqual(test["kind"], "official")
        self.assertEqual(test["minutes"], 105)
        self.assertEqual([item["question_id"] for item in test["questions"]], ["fx-001", "fx-002"])
        self.assertEqual(test["questions"][0]["choices"], self.app.bank.by_id["fx-001"]["choices"])
        self.assertEqual(test["questions"][1]["passage_image"], "crops/fx-passage.png")
        review = self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {"0": 0, "1": 2}})
        self.assertEqual(review["score"], 1)
        catalog = {(entry["set"], entry["part"]): entry for entry in self.app.request("GET", "/api/official")}
        self.assertEqual(catalog[("fx", "language")]["attempts"][0]["score"], 1)
        self.app.request("POST", "/api/tests", {"official_set": "fx", "official_part": "nope"}, expect=400)

    def test_listening_hides_spoken_choices_until_submitted(self):
        test = self.app.request("POST", "/api/tests", {"official_set": "fx", "official_part": "listening"})
        item = test["questions"][0]
        self.assertEqual(item["choices"], ["1", "2", "3"])
        self.assertTrue(item["choices_hidden"])
        self.assertNotIn("script", item)
        self.assertEqual(item["audio"]["file"], "raw/fx/fx.mp3")
        self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {"0": 3}}, expect=400)
        review = self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {"0": 0}})
        item = review["questions"][0]
        self.assertTrue(item["correct"])
        self.assertEqual(item["choices"][0], "はい、どうぞ。")
        self.assertIn("座{すわ}って", item["script"])
        self.assertTrue(item["script_translation"])

    def test_daily_tests_never_use_official_questions(self):
        for _ in range(3):
            test = self.app.request("POST", "/api/tests", {"size": 30})
            self.assertFalse([item for item in test["questions"] if item["question_id"].startswith("fx-")])
            self.app.request("POST", f"/api/tests/{test['id']}/submit", {"answers": {}})
        self.assertEqual(self.app.request("GET", "/api/summary")["bank_size"], len(self.app.bank.questions))

    def test_unfinished_official_test_does_not_replace_daily_resume(self):
        official = self.app.request("POST", "/api/tests", {"official_set": "fx", "official_part": "language"})
        self.assertIsNone(self.app.request("GET", "/api/summary")["unfinished_test"])
        catalog = {(entry["set"], entry["part"]): entry for entry in self.app.request("GET", "/api/official")}
        self.assertEqual(catalog[("fx", "language")]["unfinished"], official["id"])

    def test_assets_support_range_requests_and_stay_inside_allowed_folders(self):
        status, headers, body = self.fetch("/official/crops/fx-passage.png")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))

        size = (FIXTURE_OFFICIAL / "raw" / "fx" / "fx.mp3").stat().st_size
        status, headers, body = self.fetch("/official/raw/fx/fx.mp3", {"Range": "bytes=0-99"})
        self.assertEqual((status, headers["Content-Range"], len(body)), (206, f"bytes 0-99/{size}", 100))
        status, headers, body = self.fetch("/official/raw/fx/fx.mp3", {"Range": "bytes=-50"})
        self.assertEqual((status, len(body)), (206, 50))
        status, headers, body = self.fetch("/official/raw/fx/fx.mp3", {"Range": f"bytes={size}-"})
        self.assertEqual(status, 416)
        status, headers, body = self.fetch("/official/raw/fx/fx.mp3")
        self.assertEqual((status, headers["Accept-Ranges"], len(body)), (200, "bytes", size))

        for path in ("/official/questions/fixture.json", "/official/../../serve.py", "/official/raw/../questions/fixture.json"):
            self.assertEqual(self.fetch(path)[0], 404, path)


class OfficialBankLoadingTest(unittest.TestCase):
    def test_broken_official_bank_disables_official_tests_but_not_the_app(self):
        with tempfile.TemporaryDirectory() as directory:
            questions = Path(directory) / "questions"
            questions.mkdir()
            items = json.loads((FIXTURE_OFFICIAL / "questions" / "fixture.json").read_text(encoding="utf-8"))
            listening = next(item for item in items if item["section"] == "listening_response")
            del listening["audio"]
            items = [item for item in items if "passage_image" not in item]  # assets are not copied here
            (questions / "broken.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            bank = QuestionBank.load(QUESTIONS_DIR, questions)
        self.assertEqual(bank.official, [])
        self.assertIn("listening question needs audio", bank.warnings[0])
        self.assertTrue(bank.questions)


class MigrationTest(unittest.TestCase):
    def test_database_from_first_version_is_upgraded(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE tests (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, local_date TEXT NOT NULL,
                                    size INTEGER NOT NULL, submitted_at TEXT, score INTEGER, seconds REAL);
                INSERT INTO tests(created_at, local_date, size) VALUES ('2026-10-27T06:46:51+00:00', '2026-10-27', 10);
            """)
            connection.close()
            store = Store(path, QuestionBank.load(QUESTIONS_DIR))
            try:
                tests = store.list_tests()
                self.assertEqual((tests[0]["kind"], tests[0]["label"]), ("daily", "Mini test · 10 questions"))
                Store(path, store.bank).close()  # migrating twice is a no-op
            finally:
                store.close()
