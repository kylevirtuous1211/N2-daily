# N2 Daily

A local, offline JLPT N2 practice app: a daily mini mock test, a very detailed mistake review, and a spaced-repetition vocabulary deck.

## Requirements

- Windows 10 or 11.
  The desktop launcher and shortcut are Windows-only; other systems are untested.
- Python 3.14.
  You do not need to install it yourself: `uv` downloads it in the install step below.
  The app uses only the Python standard library, so there are no packages to install.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), for example `winget install --id=astral-sh.uv`.
- [Git](https://git-scm.com/), to clone the repo.
- Google Chrome or Microsoft Edge (recommended).
  The launcher opens the app in its own window with either one; without them it opens a tab in your default browser.
- Node.js, only if you want to run the JavaScript tests.

## Install

```
git clone <this repo's URL> n2-daily
cd n2-daily
uv venv --python 3.14 .venv
powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1
```

The last step creates the **N2 Daily** shortcut on your desktop and in the Start menu.
Cloning alone does not create it.
The shortcut points at the folder you cloned into, so run the script again if you move that folder.

The repo does not include the official JLPT workbooks (see [Official practice tests](#official-practice-tests)), so a fresh install has only the daily mini tests and the deck.

## Use it

Double-click **N2 Daily** on the desktop (or in the Start menu).
The launcher starts a small local server if it is not already running and opens the app in its own window.
The server stops by itself 15 minutes after the window is closed.

- **Today** - start the daily mini test (10, 20 or 30 questions covering every N2 language-knowledge and reading section).
- **Review** - after a test, every mistake is explained: furigana, translation, why each choice is right or wrong, and every vocabulary word and grammar pattern with an example sentence.
  Press **+ Deck** next to words you don't know, or add all words from your mistakes at once.
- **Deck** - list of saved words with their current predicted recall, search and filters, and review settings.
  **By group** shows related words together (school, work, feelings, ...; verbs with no clear subject under 動詞I / 動詞II / 動詞III), 10 per group in romaji order.
  New cards are introduced one group at a time; when reviews come back is still decided by the forgetting curve.
- **Study** - Anki-style flashcards. Keys: Space shows the answer, 1-4 rate Again / Hard / Good / Easy.
- **Dark mode** - the button at the top right cycles between matching Windows (its light or dark app mode), light and dark.
  The choice is remembered.

- **Official practice tests** - the two free official N2 workbooks from jlpt.jp (2012 and 2018), as full mock tests in the original order with the official time limits, including listening with the official audio.

Your data lives in `%LOCALAPPDATA%\N2Daily\n2daily.sqlite3`, separate from the app folder.

## Official practice tests

The official workbooks (日本語能力試験公式問題集 and 第二集) are published free at https://www.jlpt.jp/samples/sampleindex.html.
The jlpt.jp site policy allows reproducing and adapting them for personal study, so they are imported only into `content/official/`, which is git-ignored and must not be shared or published.
That folder holds the downloaded PDFs and MP3s (`raw/`), page renders (`pages/`), image crops (`crops/`) and the converted questions (`questions/`).
Official questions never appear in the daily mini tests.
If anything in the official bank fails validation, the app starts without official tests and prints a warning.

## How scheduling works

Cards are scheduled with FSRS-5, a forgetting-curve model.
Each card has a stability S (days until predicted recall falls to 90%) and recall decays as R = (1 + 19/81 * t / S) ^ -0.5.
A card comes back when its predicted recall drops to your target (90% by default), and due cards are shown most-forgotten first.
New and forgotten cards first go through short learning steps (1, 6 and 10 minutes).

Test questions are picked unseen-first; questions you got wrong come back after two days (at most a third of each section).
Choices are shuffled every time a question is shown.

## Develop

```
uv venv --python 3.14 .venv
.venv\Scripts\python.exe serve.py --port 8799 --db scratch.sqlite3   # dev server
.venv\Scripts\python.exe tools\run_tests.py                           # content validation + unit + end-to-end + JS tests
```

The app uses only the Python standard library and plain JavaScript; there is nothing to install.

- `content/questions/*.json` - the question bank; `tools/validate_content.py` checks schema and furigana markup.
- `tools/show_questions.py` and `tools/apply_fixes.py` - inspect questions by id and apply reviewed path-based fixes.
- `tools/check_readings.py` - cross-checks every furigana and vocab reading against JMdict and KANJIDIC2 (download the jmdict-simplified `jmdict-eng` and `kanjidic2-en` JSON into the git-ignored `cache/`; `run_tests.py` then runs it too).
  The dictionary data is EDRDG's, used under CC BY-SA 4.0 (https://www.edrdg.org/edrdg/licence.html).
- `content/topics.json` - the topic list and the topic of every word in the bank; `tools/validate_content.py` fails if a word has no topic or a fallback topic does not match its part of speech.
  Words that appear only in the official tests are labeled in the git-ignored `content/official/topics.json`.
- `tools/pick_words.py` - picks N2 words the bank does not test yet (with a suggested question type) for generating new questions.
  The word list `content/wordlists/n2_waller.csv` is Jonathan Waller's JLPT N2 list (CC BY, http://www.tanos.co.uk/jlpt/) as packaged by https://github.com/jamsinclair/open-anki-jlpt-decks (MIT).
  JLPT has published no official word list since 2010, so any N2 list is an estimate.
- `tools/make_icon.py` - renders `static/icon.svg` to `assets/n2daily.ico` with headless Chrome.
- `tools/install_shortcut.ps1` - recreates the desktop and Start menu shortcuts.

Furigana markup: `漢字{かんじ}` puts the reading over the kanji run before the braces, `[[...]]` underlines a target, `（　　）` is a blank, and `{{1}}`..`{{4}}` are sentence-building slots.
