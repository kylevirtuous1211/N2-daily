# N2 Daily

A local, offline JLPT N2 practice app: a daily mini mock test, a very detailed mistake review, and a spaced-repetition vocabulary deck.

## Use it

Double-click **N2 Daily** on the desktop (or in the Start menu).
The launcher starts a small local server if it is not already running and opens the app in its own window.
The server stops by itself 15 minutes after the window is closed.

- **Today** - start the daily mini test (10, 20 or 30 questions covering every N2 language-knowledge and reading section).
- **Review** - after a test, every mistake is explained: furigana, translation, why each choice is right or wrong, and every vocabulary word and grammar pattern with an example sentence.
  Press **+ Deck** next to words you don't know, or add all words from your mistakes at once.
- **Deck** - list of saved words with their current predicted recall, search and filters, and review settings.
- **Study** - Anki-style flashcards. Keys: Space shows the answer, 1-4 rate Again / Hard / Good / Easy.

Your data lives in `%LOCALAPPDATA%\N2Daily\n2daily.sqlite3`, separate from the app folder.

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
- `tools/make_icon.py` - renders `static/icon.svg` to `assets/n2daily.ico` with headless Chrome.
- `tools/install_shortcut.ps1` - recreates the desktop and Start menu shortcuts.

Furigana markup: `漢字{かんじ}` puts the reading over the kanji run before the braces, `[[...]]` underlines a target, `（　　）` is a blank, and `{{1}}`..`{{4}}` are sentence-building slots.
