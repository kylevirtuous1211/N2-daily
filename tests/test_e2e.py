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
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.bank = QuestionBank.load(QUESTIONS_DIR)
        self.store = Store(Path(self.directory.name) / "test.sqlite3", self.bank, clock=self.clock, rng=random.Random(7))
        self.server = AppServer(("127.0.0.1", 0), self.store)
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
