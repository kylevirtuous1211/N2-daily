import copy
import json
import unittest
from pathlib import Path

from n2.bank import SECTIONS, QuestionBank, load_and_validate, markup_errors, strip_markup, validate_question
from n2.store import TEST_PLANS

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "content" / "questions"
EXAMPLES = json.loads((QUESTIONS_DIR / "00_examples.json").read_text(encoding="utf-8"))


class MarkupTest(unittest.TestCase):
    def test_accepts_furigana_after_kanji_run(self):
        self.assertEqual(markup_errors("日本語{にほんご}を勉強{べんきょう}する"), [])
        self.assertEqual(markup_errors("考{かんが}える[[慎重]]"), [])
        self.assertEqual(markup_errors("時々{ときどき}"), [])

    def test_rejects_furigana_without_kanji(self):
        self.assertTrue(markup_errors("ひらがな{ひらがな}"))

    def test_rejects_non_kana_reading(self):
        self.assertTrue(markup_errors("漢字{kanji}"))

    def test_rejects_unbalanced_target(self):
        self.assertTrue(markup_errors("[[慎重に"))

    def test_strip_markup(self):
        self.assertEqual(strip_markup("[[慎重]]に考{かんが}える {{1}}"), "慎重に考える ＿＿")


class ValidationTest(unittest.TestCase):
    def test_examples_are_valid(self):
        for question in EXAMPLES:
            self.assertEqual(validate_question(question), [], question["id"])

    def test_sentence_order_answer_must_match_star(self):
        question = copy.deepcopy(next(q for q in EXAMPLES if q["section"] == "sentence_order"))
        question["answer"] = 0
        self.assertTrue(any("correct_order" in str(error) for error in validate_question(question)))

    def test_kanji_reading_target_may_not_reveal_reading(self):
        question = copy.deepcopy(next(q for q in EXAMPLES if q["section"] == "kanji_reading"))
        question["question"] = question["question"].replace("[[慎重]]", "[[慎重{しんちょう}]]")
        self.assertTrue(validate_question(question))

    def test_duplicate_choices_rejected(self):
        question = copy.deepcopy(EXAMPLES[0])
        question["choices"][1] = question["choices"][0]
        self.assertTrue(validate_question(question))


class ShippedBankTest(unittest.TestCase):
    """The real question bank must load cleanly and cover every daily-test slot."""

    def test_bank_has_no_errors(self):
        _, errors = load_and_validate(QUESTIONS_DIR)
        self.assertEqual([str(error) for error in errors], [])

    def test_bank_covers_largest_test_plan(self):
        bank = QuestionBank.load(QUESTIONS_DIR)
        largest = TEST_PLANS[max(TEST_PLANS)]
        for section in SECTIONS:
            self.assertGreaterEqual(len(bank.by_section[section]), largest.get(section, 0) * 3, section)

    def test_answers_are_spread_across_positions(self):
        bank = QuestionBank.load(QUESTIONS_DIR)
        counts = [sum(1 for q in bank.questions if q["answer"] == index) for index in range(4)]
        self.assertGreater(min(counts), len(bank.questions) * 0.12, counts)


if __name__ == "__main__":
    unittest.main()
