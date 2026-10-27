"""The reading checker must flag real misreadings and accept legitimate sound changes (needs cache/ JMdict data)."""

import unittest
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "cache"
HAS_DICTIONARY = any(CACHE.glob("jmdict-eng-*.json")) and any(CACHE.glob("kanjidic2-en-*.json"))


@unittest.skipUnless(HAS_DICTIONARY, "JMdict/KANJIDIC2 JSON not downloaded into cache/")
class CheckReadingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools import check_readings
        cls.module = check_readings
        cls.dictionary = check_readings.Dictionary()

    def problems(self, text):
        return [(base, reading) for base, reading, before in self.module.ruby_runs(text)
                if self.module.check_run(self.dictionary, base, reading, before)]

    def test_flags_misreadings(self):
        for text in ("[[慎重{しんじゅう}]]に", "態度{だいど}", "範囲{はんいん}", "柔軟{にゅうなん}な", "迫{せめ}る"):
            self.assertTrue(self.problems(text), text)

    def test_accepts_legitimate_readings(self):
        for text in ("まだ二{に}、三日{さんにち}は", "百歳{ひゃくさい}", "五十{ごじゅっ}ページ", "旅行{りょこう}会社{がいしゃ}",
                     "気持{きも}ち", "流行{はや}る", "お腹{なか}", "ゴミ袋{ぶくろ}", "時々{ときどき}", "一人{ひとり}",
                     "今日{きょう}", "引{ひ}っ張{ぱ}る", "十分{じゅっぷん}", "水{みず}浸{びた}し"):
            self.assertEqual(self.problems(text), [], text)

    def test_headwords(self):
        check = self.module.check_headword
        self.assertIsNone(check(self.dictionary, "慎重", "しんちょう"))
        self.assertIsNone(check(self.dictionary, "小雨決行", "こさめけっこう"))
        self.assertEqual(check(self.dictionary, "慎重", "しんじゅう"), "not-listed")
        self.assertEqual(self.module.normalize_word("とても〜ない"), "")


if __name__ == "__main__":
    unittest.main()
