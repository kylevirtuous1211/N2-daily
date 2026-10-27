"""FSRS-5 spaced-repetition scheduler (forgetting-curve based).

Memory model:
    retrievability R(t, S) = (1 + FACTOR * t / S) ** DECAY
where t is days since the last review and S is stability (days until R drops to 90%).

New and lapsed cards go through short learning steps (minutes) like Anki before
they graduate to day-based intervals derived from stability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

DECAY = -0.5
FACTOR = 19 / 81

# FSRS-5 default parameters.
DEFAULT_WEIGHTS = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575,
    0.1192, 1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621,
)

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATINGS = (AGAIN, HARD, GOOD, EASY)

NEW, LEARNING, REVIEW, RELEARNING = "new", "learning", "review", "relearning"

LEARNING_STEPS = {AGAIN: timedelta(minutes=1), HARD: timedelta(minutes=6), GOOD: timedelta(minutes=10)}
RELEARNING_STEP = timedelta(minutes=10)
MAX_INTERVAL_DAYS = 36500


@dataclass(frozen=True)
class CardState:
    state: str = NEW
    stability: float = 0.0
    difficulty: float = 0.0
    due: datetime | None = None
    last_review: datetime | None = None
    reps: int = 0
    lapses: int = 0


def retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return (1 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY


def interval_for(stability: float, desired_retention: float) -> int:
    """Days until predicted recall falls to desired_retention."""
    days = stability / FACTOR * (desired_retention ** (1 / DECAY) - 1)
    return int(min(max(round(days), 1), MAX_INTERVAL_DAYS))


class Scheduler:
    def __init__(self, weights: tuple[float, ...] = DEFAULT_WEIGHTS, desired_retention: float = 0.9):
        if len(weights) != 19:
            raise ValueError("FSRS-5 needs 19 weights")
        self.weights = weights
        self.desired_retention = desired_retention

    # --- core formulas -------------------------------------------------

    def initial_stability(self, rating: int) -> float:
        return max(self.weights[rating - 1], 0.1)

    def initial_difficulty(self, rating: int) -> float:
        weights = self.weights
        return _clamp_difficulty(weights[4] - math.exp(weights[5] * (rating - 1)) + 1)

    def next_difficulty(self, difficulty: float, rating: int) -> float:
        weights = self.weights
        delta = -weights[6] * (rating - 3)
        damped = difficulty + delta * (10 - difficulty) / 9
        reverted = weights[7] * self.initial_difficulty(EASY) + (1 - weights[7]) * damped
        return _clamp_difficulty(reverted)

    def recall_stability(self, difficulty: float, stability: float, recall: float, rating: int) -> float:
        weights = self.weights
        hard_penalty = weights[15] if rating == HARD else 1.0
        easy_bonus = weights[16] if rating == EASY else 1.0
        growth = (
            math.exp(weights[8])
            * (11 - difficulty)
            * stability ** -weights[9]
            * (math.exp(weights[10] * (1 - recall)) - 1)
            * hard_penalty
            * easy_bonus
        )
        return stability * (growth + 1)

    def forget_stability(self, difficulty: float, stability: float, recall: float) -> float:
        weights = self.weights
        new_stability = (
            weights[11]
            * difficulty ** -weights[12]
            * ((stability + 1) ** weights[13] - 1)
            * math.exp(weights[14] * (1 - recall))
        )
        return min(new_stability, stability)

    def short_term_stability(self, stability: float, rating: int) -> float:
        weights = self.weights
        return stability * math.exp(weights[17] * (rating - 3 + weights[18]))

    # --- scheduling ----------------------------------------------------

    def review(self, card: CardState, rating: int, now: datetime) -> CardState:
        if rating not in RATINGS:
            raise ValueError(f"rating must be one of {RATINGS}")

        if card.state == NEW:
            return self._review_new(card, rating, now)

        elapsed_days = _elapsed_days(card.last_review, now)
        difficulty = self.next_difficulty(card.difficulty, rating)

        if elapsed_days < 1:
            stability = self.short_term_stability(card.stability, rating)
        elif rating == AGAIN:
            recall = retrievability(elapsed_days, card.stability)
            stability = self.forget_stability(card.difficulty, card.stability, recall)
        else:
            recall = retrievability(elapsed_days, card.stability)
            stability = self.recall_stability(card.difficulty, card.stability, recall, rating)

        stability = max(stability, 0.1)
        base = replace(card, stability=stability, difficulty=difficulty, last_review=now, reps=card.reps + 1)

        if card.state in (LEARNING, RELEARNING):
            if rating in (AGAIN, HARD):
                return replace(base, due=now + LEARNING_STEPS[rating])
            return self._graduate(base, now)

        # REVIEW state
        if rating == AGAIN:
            return replace(base, state=RELEARNING, due=now + RELEARNING_STEP, lapses=card.lapses + 1)
        return self._graduate(base, now)

    def preview(self, card: CardState, now: datetime) -> dict[int, CardState]:
        return {rating: self.review(card, rating, now) for rating in RATINGS}

    def _review_new(self, card: CardState, rating: int, now: datetime) -> CardState:
        base = replace(
            card,
            stability=self.initial_stability(rating),
            difficulty=self.initial_difficulty(rating),
            last_review=now,
            reps=1,
        )
        if rating == EASY:
            return self._graduate(base, now)
        return replace(base, state=LEARNING, due=now + LEARNING_STEPS[rating])

    def _graduate(self, card: CardState, now: datetime) -> CardState:
        days = interval_for(card.stability, self.desired_retention)
        return replace(card, state=REVIEW, due=now + timedelta(days=days))


def _clamp_difficulty(value: float) -> float:
    return min(max(value, 1.0), 10.0)


def _elapsed_days(last_review: datetime | None, now: datetime) -> float:
    if last_review is None:
        return 0.0
    return max((now - last_review).total_seconds() / 86400, 0.0)


def current_retrievability(card: CardState, now: datetime) -> float | None:
    if card.state == NEW or card.last_review is None:
        return None
    return retrievability(_elapsed_days(card.last_review, now), card.stability)
