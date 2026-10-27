import unittest
from datetime import datetime, timedelta, timezone

from n2 import fsrs

NOW = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def days_until_due(card: fsrs.CardState, now: datetime) -> float:
    return (card.due - now).total_seconds() / 86400


class ForgettingCurveTest(unittest.TestCase):
    def test_recall_is_ninety_percent_after_one_stability(self):
        self.assertAlmostEqual(fsrs.retrievability(10, 10), 0.9, places=6)
        self.assertEqual(fsrs.retrievability(0, 10), 1.0)

    def test_recall_decays_monotonically(self):
        values = [fsrs.retrievability(days, 5) for days in range(0, 60, 5)]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_interval_matches_stability_at_ninety_percent(self):
        self.assertEqual(fsrs.interval_for(10, 0.9), 10)
        self.assertGreater(fsrs.interval_for(10, 0.8), fsrs.interval_for(10, 0.9))
        self.assertEqual(fsrs.interval_for(0.01, 0.9), 1)


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.scheduler = fsrs.Scheduler()

    def graduated_card(self) -> fsrs.CardState:
        learning = self.scheduler.review(fsrs.CardState(), fsrs.GOOD, NOW)
        return self.scheduler.review(learning, fsrs.GOOD, learning.due)

    def test_new_card_learning_steps(self):
        card = fsrs.CardState()
        again = self.scheduler.review(card, fsrs.AGAIN, NOW)
        good = self.scheduler.review(card, fsrs.GOOD, NOW)
        easy = self.scheduler.review(card, fsrs.EASY, NOW)
        self.assertEqual((again.state, again.due - NOW), (fsrs.LEARNING, timedelta(minutes=1)))
        self.assertEqual((good.state, good.due - NOW), (fsrs.LEARNING, timedelta(minutes=10)))
        self.assertEqual(easy.state, fsrs.REVIEW)
        self.assertEqual(round(days_until_due(easy, NOW)), round(fsrs.DEFAULT_WEIGHTS[3]))
        self.assertGreater(again.difficulty, easy.difficulty)

    def test_learning_card_graduates_on_good(self):
        card = self.graduated_card()
        self.assertEqual(card.state, fsrs.REVIEW)
        self.assertGreaterEqual(days_until_due(card, card.last_review), 1)
        self.assertEqual(card.reps, 2)

    def test_successful_review_on_time_grows_stability(self):
        card = self.graduated_card()
        later = self.scheduler.review(card, fsrs.GOOD, card.due)
        self.assertGreater(later.stability, card.stability)
        self.assertGreater(days_until_due(later, card.due), days_until_due(card, card.last_review))

    def test_late_review_grows_stability_more_than_early(self):
        card = self.graduated_card()
        early = self.scheduler.review(card, fsrs.GOOD, card.last_review + timedelta(days=1))
        late = self.scheduler.review(card, fsrs.GOOD, card.due + timedelta(days=5))
        self.assertGreater(late.stability, early.stability)

    def test_lapse_moves_to_relearning_and_cuts_stability(self):
        card = self.graduated_card()
        lapsed = self.scheduler.review(card, fsrs.AGAIN, card.due)
        self.assertEqual(lapsed.state, fsrs.RELEARNING)
        self.assertEqual(lapsed.lapses, 1)
        self.assertLess(lapsed.stability, card.stability)
        self.assertEqual(lapsed.due - card.due, fsrs.RELEARNING_STEP)
        relearned = self.scheduler.review(lapsed, fsrs.GOOD, lapsed.due)
        self.assertEqual(relearned.state, fsrs.REVIEW)

    def test_ratings_order_intervals_for_review_cards(self):
        card = self.graduated_card()
        previews = self.scheduler.preview(card, card.due)
        intervals = [previews[rating].due - card.due for rating in (fsrs.HARD, fsrs.GOOD, fsrs.EASY)]
        self.assertEqual(intervals, sorted(intervals))
        self.assertLess(intervals[0], intervals[2])

    def test_difficulty_stays_in_bounds(self):
        card = self.graduated_card()
        moment = card.due
        for _ in range(30):
            card = self.scheduler.review(card, fsrs.AGAIN, moment)
            moment = card.due
        self.assertLessEqual(card.difficulty, 10)
        for _ in range(30):
            card = self.scheduler.review(card, fsrs.EASY, moment)
            moment = card.due
        self.assertGreaterEqual(card.difficulty, 1)

    def test_higher_retention_gives_shorter_intervals(self):
        strict = fsrs.Scheduler(desired_retention=0.95).review(fsrs.CardState(), fsrs.EASY, NOW)
        relaxed = fsrs.Scheduler(desired_retention=0.8).review(fsrs.CardState(), fsrs.EASY, NOW)
        self.assertLess(strict.due, relaxed.due)

    def test_rejects_invalid_rating(self):
        with self.assertRaises(ValueError):
            self.scheduler.review(fsrs.CardState(), 5, NOW)


if __name__ == "__main__":
    unittest.main()
