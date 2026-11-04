import unittest

from n2.topics import romaji


class RomajiTest(unittest.TestCase):
    def test_hepburn_spelling(self):
        cases = {
            "きちょう": "kichou", "しゃかい": "shakai", "ちゅうい": "chuui", "じゃま": "jama", "ぢゃ": "ja",
            "がっこう": "gakkou", "きっぷ": "kippu", "まっちゃ": "matcha", "しゅっちょう": "shutchou",
            "しんぶん": "shinbun", "ふゆ": "fuyu", "つくえ": "tsukue",
        }
        for kana, expected in cases.items():
            self.assertEqual(romaji(kana), expected, kana)

    def test_katakana_long_vowels_and_foreign_sounds(self):
        cases = {"コンピューター": "konpyuutaa", "パーティー": "paatii", "ファイル": "fairu", "ウィルス": "wirusu",
                 "ジェット": "jetto", "チェック": "chekku"}
        for kana, expected in cases.items():
            self.assertEqual(romaji(kana), expected, kana)

    def test_ignores_non_kana(self):
        self.assertEqual(romaji("〜かどうか"), "kadouka")
        self.assertEqual(romaji("〜ことができる"), "kotogadekiru")


if __name__ == "__main__":
    unittest.main()
