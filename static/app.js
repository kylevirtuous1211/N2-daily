import { escapeHtml, plainJa, renderJa } from "./markup.js";

const app = document.getElementById("app");
const toastElement = document.getElementById("toast");
const LEARN_AHEAD_MS = 20 * 60 * 1000;
const CHOICE_LABELS = ["1", "2", "3", "4"];
const RATING_NAMES = { 1: "Again", 2: "Hard", 3: "Good", 4: "Easy" };
const CLOSE_ICON = `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
const STATE_NAMES = { new: "New", learning: "Learning", review: "Review", relearning: "Relearning" };

let cleanupView = () => {};

// --- infrastructure ------------------------------------------------------

async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Can't reach the N2 Daily server (it stops after a while when unused). Close this window and open N2 Daily from the desktop shortcut again - your progress is saved.");
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function toast(message) {
  toastElement.textContent = message;
  toastElement.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => toastElement.classList.remove("visible"), 2200);
}

function formatDuration(seconds) {
  if (seconds == null) return "-";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

function formatInterval(seconds) {
  if (seconds < 60) return "<1m";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  const days = seconds / 86400;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

function formatDue(isoText) {
  if (!isoText) return "-";
  const seconds = (new Date(isoText) - Date.now()) / 1000;
  if (seconds <= 0) return "now";
  return `in ${formatInterval(seconds)}`;
}

function formatDate(isoDate) {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", weekday: "short" });
}

function percent(part, whole) {
  return whole ? Math.round((part / whole) * 100) : 0;
}

function vocabKey(entry) {
  return `vocab:${entry.word}:${entry.reading}`;
}

function grammarKey(entry) {
  return `grammar:${entry.pattern}`;
}

function setActiveNav(name) {
  for (const link of document.querySelectorAll("[data-nav]")) {
    link.classList.toggle("active", link.dataset.nav === name);
  }
}

const japaneseVoice = () => speechSynthesis.getVoices().find((voice) => voice.lang.replace("_", "-").startsWith("ja"));

function speak(text) {
  const voice = japaneseVoice();
  if (!voice) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.rate = 0.9;
  speechSynthesis.speak(utterance);
}

function speakButton(text) {
  if (!("speechSynthesis" in window) || !japaneseVoice()) return "";
  return `<button class="icon-button" data-speak="${escapeHtml(text)}" title="Listen" aria-label="Listen">🔊</button>`;
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-speak]");
  if (button) speak(button.dataset.speak);
});

setInterval(() => api("POST", "/api/heartbeat").catch(() => {}), 60_000);

// --- router --------------------------------------------------------------

const routes = [
  [/^#?\/?$/, viewHome, "home"],
  [/^#\/test\/(\d+)$/, viewTest, "home"],
  [/^#\/review\/(\d+)$/, viewReview, "history"],
  [/^#\/deck$/, viewDeck, "deck"],
  [/^#\/study$/, viewStudy, "study"],
  [/^#\/history$/, viewHistory, "history"],
];

async function route() {
  cleanupView();
  cleanupView = () => {};
  const hash = location.hash || "#/";
  for (const [pattern, view, nav] of routes) {
    const match = hash.match(pattern);
    if (!match) continue;
    setActiveNav(nav);
    window.scrollTo(0, 0);
    try {
      await view(...match.slice(1));
    } catch (error) {
      app.innerHTML = `<section class="card error-card"><h2>Something went wrong</h2><p>${escapeHtml(error.message)}</p><a class="button" href="#/">Back to Today</a></section>`;
    }
    return;
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", route);
if ("speechSynthesis" in window) speechSynthesis.addEventListener("voiceschanged", () => {});
route();

// --- home ----------------------------------------------------------------

async function viewHome() {
  const summary = await api("GET", "/api/summary");
  const doneToday = summary.today_tests.filter((test) => test.submitted_at);
  const unfinished = summary.unfinished_test;
  const best = doneToday[0];

  let testCard;
  if (unfinished) {
    testCard = `
      <p class="lead">You have an unfinished mini test from ${formatDate(unfinished.local_date)}.</p>
      <div class="actions">
        <a class="button primary" href="#/test/${unfinished.id}">Resume test</a>
        <button class="button ghost" data-discard="${unfinished.id}">Discard it</button>
      </div>`;
  } else if (best) {
    testCard = `
      <p class="lead done">Done for today: <strong>${best.score} / ${best.size}</strong> (${percent(best.score, best.size)}%) in ${formatDuration(best.seconds)}.</p>
      <div class="actions">
        <a class="button primary" href="#/review/${best.id}">Review mistakes</a>
        ${sizePicker("Another test")}
      </div>`;
  } else {
    testCard = `
      <p class="lead">A short mock test with every N2 section: kanji, vocabulary, grammar, sentence building and reading.</p>
      <div class="actions">${sizePicker("Start", true)}</div>`;
  }

  const stats = summary.section_stats;
  const sectionRows = Object.entries(summary.sections).map(([key, meta]) => {
    const entry = stats[key];
    const rate = percent(entry.correct, entry.answered);
    return `
      <div class="section-row">
        <div class="section-name"><span class="ja">${meta.ja}</span><span class="muted">${meta.en}</span></div>
        <div class="meter" title="${entry.correct} / ${entry.answered}"><span style="width:${entry.answered ? rate : 0}%"></span></div>
        <div class="section-rate">${entry.answered ? `${rate}%` : "-"}</div>
      </div>`;
  }).join("");

  const studyCount = summary.due_now + summary.new_available;
  app.innerHTML = `
    <section class="hero card">
      <div class="hero-head">
        <div>
          <p class="eyebrow">${formatDate(summary.today)}</p>
          <h1>Today's mini test</h1>
        </div>
        <div class="streak" title="Days in a row with a finished test">
          <span class="streak-number">${summary.streak}</span>
          <span class="streak-label">day streak</span>
        </div>
      </div>
      ${testCard}
    </section>

    <div class="grid two">
      <section class="card">
        <h2>Vocabulary review</h2>
        <div class="stat-row">
          <div class="stat"><span class="stat-number">${summary.due_now}</span><span class="stat-label">due now</span></div>
          <div class="stat"><span class="stat-number">${summary.new_available}</span><span class="stat-label">new today</span></div>
          <div class="stat"><span class="stat-number">${summary.deck_size}</span><span class="stat-label">in deck</span></div>
        </div>
        <div class="actions">
          ${studyCount ? `<a class="button primary" href="#/study">Study ${studyCount} card${studyCount === 1 ? "" : "s"}</a>` : `<span class="muted">Nothing due right now${summary.reviewed_today ? ` - ${summary.reviewed_today} reviews done today` : ""}.</span>`}
          <a class="button ghost" href="#/deck">Open deck</a>
        </div>
      </section>
      <section class="card">
        <h2>Accuracy by section</h2>
        <div class="sections">${sectionRows}</div>
        <p class="muted small">${summary.seen_questions} of ${summary.bank_size} questions seen.</p>
      </section>
    </div>`;

  app.querySelector("[data-discard]")?.addEventListener("click", async (event) => {
    if (!confirm("Discard the unfinished test?")) return;
    await api("DELETE", `/api/tests/${event.target.dataset.discard}`);
    localStorage.removeItem(`n2-test-${event.target.dataset.discard}`);
    route();
  });
  for (const button of app.querySelectorAll("[data-size]")) {
    button.addEventListener("click", () => startTest(Number(button.dataset.size)));
  }
}

function sizePicker(label, primary = false) {
  return `
    <div class="size-picker">
      <button class="button ${primary ? "primary" : ""}" data-size="20">${label}: 20 questions <span class="muted-inline">~25 min</span></button>
      <button class="button ghost" data-size="10">10 <span class="muted-inline">~12 min</span></button>
      <button class="button ghost" data-size="30">30 <span class="muted-inline">~40 min</span></button>
    </div>`;
}

async function startTest(size) {
  const test = await api("POST", "/api/tests", { size });
  location.hash = `#/test/${test.id}`;
}

// --- test ----------------------------------------------------------------

async function viewTest(testId) {
  const [test, settings] = await Promise.all([api("GET", `/api/tests/${testId}`), api("GET", "/api/settings")]);
  if (test.submitted) {
    location.hash = `#/review/${test.id}`;
    return;
  }
  const storageKey = `n2-test-${test.id}`;
  const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
  const progress = {
    answers: saved.answers || {},
    current: Math.min(saved.current || 0, test.questions.length - 1),
    elapsedMs: saved.elapsedMs || 0,
    furigana: saved.furigana ?? settings.test_furigana,
  };
  let resumedAt = Date.now();
  const elapsed = () => progress.elapsedMs + (Date.now() - resumedAt);
  const save = () => localStorage.setItem(storageKey, JSON.stringify({ ...progress, elapsedMs: elapsed() }));

  app.innerHTML = `
    <section class="test-shell">
      <div class="test-toolbar">
        <div class="progress-dots" role="tablist"></div>
        <div class="toolbar-right">
          <label class="switch"><input type="checkbox" data-furigana ${progress.furigana ? "checked" : ""}><span>Furigana</span></label>
          <span class="timer" title="Elapsed time">0:00</span>
        </div>
      </div>
      <article class="card question-card"></article>
      <div class="test-nav">
        <button class="button ghost" data-prev>← Previous</button>
        <span class="muted small keys-hint">Keys: 1-4 choose · ← → move</span>
        <button class="button" data-next>Next →</button>
      </div>
    </section>`;

  const card = app.querySelector(".question-card");
  const dots = app.querySelector(".progress-dots");
  const timer = app.querySelector(".timer");
  const nextButton = app.querySelector("[data-next]");
  const prevButton = app.querySelector("[data-prev]");

  const renderDots = () => {
    dots.innerHTML = test.questions.map((question, index) => `
      <button class="dot ${index === progress.current ? "current" : ""} ${progress.answers[index] != null ? "answered" : ""}"
        data-goto="${index}" title="Question ${index + 1}" aria-label="Question ${index + 1}">${index + 1}</button>`).join("");
  };

  const render = () => {
    const question = test.questions[progress.current];
    const meta = test.sections[question.section];
    const isLast = progress.current === test.questions.length - 1;
    card.classList.toggle("furigana-off", !progress.furigana);
    card.innerHTML = `
      <header class="question-head">
        <span class="badge">${meta.ja}</span>
        <span class="muted">${meta.en} · Question ${progress.current + 1} of ${test.questions.length}</span>
      </header>
      <p class="instructions ja">${escapeHtml(meta.instructions)}</p>
      ${questionBody(question)}
      <ol class="choices">
        ${question.choices.map((choice, index) => `
          <li><button class="choice ${progress.answers[progress.current] === index ? "selected" : ""}" data-choice="${index}">
            <span class="choice-number">${CHOICE_LABELS[index]}</span><span class="ja">${renderJa(choice)}</span>
          </button></li>`).join("")}
      </ol>`;
    prevButton.disabled = progress.current === 0;
    nextButton.textContent = isLast ? "Finish & see results" : "Next →";
    nextButton.classList.toggle("primary", isLast);
    renderDots();
  };

  const move = (index) => {
    progress.current = Math.max(0, Math.min(index, test.questions.length - 1));
    save();
    render();
    window.scrollTo(0, 0);
  };

  const choose = (index) => {
    progress.answers[progress.current] = index;
    save();
    render();
  };

  const finish = async () => {
    const unanswered = test.questions.length - Object.keys(progress.answers).length;
    if (unanswered && !confirm(`${unanswered} question${unanswered === 1 ? " is" : "s are"} unanswered. Finish anyway?`)) return;
    nextButton.disabled = true;
    await api("POST", `/api/tests/${test.id}/submit`, { answers: progress.answers, seconds: elapsed() / 1000 });
    localStorage.removeItem(storageKey);
    location.hash = `#/review/${test.id}`;
  };

  card.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-choice]");
    if (choice) choose(Number(choice.dataset.choice));
  });
  dots.addEventListener("click", (event) => {
    const dot = event.target.closest("[data-goto]");
    if (dot) move(Number(dot.dataset.goto));
  });
  prevButton.addEventListener("click", () => move(progress.current - 1));
  nextButton.addEventListener("click", () => (progress.current === test.questions.length - 1 ? finish() : move(progress.current + 1)));
  app.querySelector("[data-furigana]").addEventListener("change", (event) => {
    progress.furigana = event.target.checked;
    save();
    card.classList.toggle("furigana-off", !progress.furigana);
    api("PATCH", "/api/settings", { test_furigana: progress.furigana }).catch(() => {});
  });

  const onKey = (event) => {
    if (event.target.matches?.("input, textarea")) return;
    if (["1", "2", "3", "4"].includes(event.key)) choose(Number(event.key) - 1);
    else if (event.key === "ArrowRight") move(progress.current + 1);
    else if (event.key === "ArrowLeft") move(progress.current - 1);
  };
  const onVisibility = () => {
    if (document.hidden) {
      progress.elapsedMs = elapsed();
      save();
    } else {
      resumedAt = Date.now();
    }
  };
  document.addEventListener("keydown", onKey);
  document.addEventListener("visibilitychange", onVisibility);
  const tick = setInterval(() => { timer.textContent = formatDuration(elapsed() / 1000); }, 1000);
  timer.textContent = formatDuration(elapsed() / 1000);
  cleanupView = () => {
    clearInterval(tick);
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("visibilitychange", onVisibility);
    save();
  };
  render();
}

function questionBody(question, slotPieces) {
  const passage = question.passage
    ? `<div class="passage ja">${renderJa(question.passage).replaceAll("\n", "<br>")}</div>`
    : "";
  if (question.section === "sentence_order") {
    const slot = (number) => {
      const isStar = number === question.star;
      const content = slotPieces ? slotPieces[number - 1] : isStar ? "★" : "";
      return `<span class="slot ${isStar ? "star" : ""}">${content}</span>`;
    };
    return `${passage}<p class="stem ja">${renderJa(question.question, { slot })}</p>`;
  }
  if (question.section === "usage") {
    return `<p class="stem usage-word ja">${renderJa(question.question)}</p>`;
  }
  return `${passage}<p class="stem ja">${renderJa(question.question)}</p>`;
}

// --- review ----------------------------------------------------------------

async function viewReview(testId) {
  const [test, keys] = await Promise.all([api("GET", `/api/tests/${testId}`), api("GET", "/api/cards/keys")]);
  if (!test.submitted) {
    location.hash = `#/test/${test.id}`;
    return;
  }
  const deckKeys = new Set(keys);
  const wrong = test.questions.filter((question) => !question.correct);
  let showAll = wrong.length === 0;
  let furigana = true;

  const bySection = {};
  for (const question of test.questions) {
    const entry = (bySection[question.section] ??= { total: 0, correct: 0 });
    entry.total += 1;
    entry.correct += question.correct ? 1 : 0;
  }

  const render = () => {
    const visible = showAll ? test.questions : wrong;
    const wrongVocab = wrong.flatMap((question) => question.vocab).filter((entry) => !deckKeys.has(vocabKey(entry)));
    const uniqueWrongVocab = [...new Map(wrongVocab.map((entry) => [vocabKey(entry), entry])).values()];
    app.innerHTML = `
      <section class="card review-summary">
        <div class="score-block">
          <p class="eyebrow">${formatDate(test.local_date)} · ${formatDuration(test.seconds)}</p>
          <h1>${test.score} / ${test.size} <span class="score-percent">${percent(test.score, test.size)}%</span></h1>
        </div>
        <div class="section-chips">
          ${Object.entries(bySection).map(([section, entry]) => `
            <span class="chip ${entry.correct === entry.total ? "good" : "bad"}">${test.sections[section].ja} ${entry.correct}/${entry.total}</span>`).join("")}
        </div>
        <div class="review-controls">
          <div class="segmented">
            <button class="${showAll ? "" : "active"}" data-filter="wrong">Mistakes (${wrong.length})</button>
            <button class="${showAll ? "active" : ""}" data-filter="all">All (${test.questions.length})</button>
          </div>
          <label class="switch"><input type="checkbox" data-furigana ${furigana ? "checked" : ""}><span>Furigana</span></label>
          ${uniqueWrongVocab.length ? `<button class="button primary" data-add-all-wrong>Add all ${uniqueWrongVocab.length} words from mistakes to deck</button>` : ""}
        </div>
      </section>
      <div class="review-list ${furigana ? "" : "furigana-off"}">
        ${visible.length ? visible.map((question) => reviewCard(question, test.sections, deckKeys)).join("") : `<section class="card"><p class="lead">No mistakes - perfect score! 🎉</p></section>`}
      </div>
      <div class="actions center"><a class="button" href="#/">Back to Today</a></div>`;
  };

  app.addEventListener("click", onReviewClick);
  app.addEventListener("change", onReviewChange);
  cleanupView = () => {
    app.removeEventListener("click", onReviewClick);
    app.removeEventListener("change", onReviewChange);
  };

  async function addCards(entries) {
    for (const { kind, data, source } of entries) {
      await api("POST", "/api/cards", { kind, data, source_question: source });
      deckKeys.add(kind === "vocab" ? vocabKey(data) : grammarKey(data));
    }
  }

  async function onReviewClick(event) {
    const filter = event.target.closest("[data-filter]");
    if (filter) {
      showAll = filter.dataset.filter === "all";
      render();
      return;
    }
    const addButton = event.target.closest("[data-add]");
    if (addButton) {
      const question = test.questions[Number(addButton.dataset.question)];
      const [kind, index] = addButton.dataset.add.split(":");
      const data = kind === "vocab" ? question.vocab[Number(index)] : question.grammar[Number(index)];
      await addCards([{ kind, data, source: question.question_id }]);
      toast(`Added ${kind === "vocab" ? data.word : data.pattern} to your deck`);
      rerenderKeepingScroll();
      return;
    }
    const addQuestion = event.target.closest("[data-add-question]");
    if (addQuestion) {
      const question = test.questions[Number(addQuestion.dataset.addQuestion)];
      const missing = question.vocab.filter((entry) => !deckKeys.has(vocabKey(entry)));
      await addCards(missing.map((data) => ({ kind: "vocab", data, source: question.question_id })));
      toast(`Added ${missing.length} word${missing.length === 1 ? "" : "s"} to your deck`);
      rerenderKeepingScroll();
      return;
    }
    if (event.target.closest("[data-add-all-wrong]")) {
      const entries = [];
      for (const question of wrong) {
        for (const data of question.vocab) {
          if (!deckKeys.has(vocabKey(data))) entries.push({ kind: "vocab", data, source: question.question_id });
        }
      }
      const unique = [...new Map(entries.map((entry) => [vocabKey(entry.data), entry])).values()];
      await addCards(unique);
      toast(`Added ${unique.length} words to your deck`);
      rerenderKeepingScroll();
      return;
    }
    const toggle = event.target.closest("[data-toggle-translation]");
    if (toggle) {
      toggle.closest(".passage-block").classList.toggle("show-translation");
    }
  }

  function onReviewChange(event) {
    if (!event.target.matches("[data-furigana]")) return;
    furigana = event.target.checked;
    app.querySelector(".review-list").classList.toggle("furigana-off", !furigana);
  }

  function rerenderKeepingScroll() {
    const scroll = window.scrollY;
    render();
    window.scrollTo(0, scroll);
  }

  render();
}

function reviewCard(question, sections, deckKeys) {
  const meta = sections[question.section];
  const index = question.position;
  const slotPieces = question.section === "sentence_order"
    ? question.correct_order.map((choiceIndex) => renderJa(question.choices[choiceIndex]))
    : null;

  const choices = question.choices.map((choice, choiceIndex) => {
    const isAnswer = choiceIndex === question.answer;
    const isChosen = choiceIndex === question.chosen;
    const status = isAnswer ? "answer" : isChosen ? "chosen-wrong" : "";
    const tag = isAnswer ? `<span class="tag good">${isChosen ? "Your answer · Correct" : "Correct answer"}</span>`
      : isChosen ? `<span class="tag bad">Your answer</span>` : "";
    return `
      <li class="review-choice ${status}">
        <div class="review-choice-head"><span class="choice-number">${CHOICE_LABELS[choiceIndex]}</span><span class="ja">${renderJa(choice)}</span>${tag}</div>
        <p class="choice-note">${escapeHtml(question.choice_notes[choiceIndex])}</p>
      </li>`;
  }).join("");

  const passage = question.passage ? `
    <div class="passage-block">
      <div class="passage ja">${renderJa(question.passage).replaceAll("\n", "<br>")}</div>
      <button class="link-button" data-toggle-translation>Show / hide English translation</button>
      <p class="passage-translation">${escapeHtml(question.passage_translation)}</p>
    </div>` : "";

  const stem = question.section === "sentence_order"
    ? `<p class="stem ja">${renderJa(question.question, { slot: (number) => `<span class="slot ${number === question.star ? "star" : ""}">${slotPieces[number - 1]}</span>` })}</p>`
    : question.section === "usage"
      ? `<p class="stem usage-word ja">${renderJa(question.question)}</p>`
      : `<p class="stem ja">${renderJa(question.question)}</p>`;

  const completed = question.full_sentence ? `
    <div class="completed">
      <p class="label">Correct sentence</p>
      <p class="ja big-ja">${renderJa(question.full_sentence)} ${speakButton(plainJa(question.full_sentence))}</p>
    </div>` : "";

  const vocabRows = question.vocab.map((entry, vocabIndex) => `
    <div class="vocab-item">
      <div class="vocab-word">
        <span class="vocab-reading">${escapeHtml(entry.reading)}</span>
        <span class="vocab-kanji ja">${escapeHtml(entry.word)}</span>
      </div>
      <div class="vocab-body">
        <p><strong>${escapeHtml(entry.meaning)}</strong> <span class="pos">${escapeHtml(entry.pos)}</span> ${speakButton(entry.word)}</p>
        <p class="example ja">${renderJa(entry.example)}</p>
        <p class="example-en">${escapeHtml(entry.example_translation)}</p>
      </div>
      <div class="vocab-action">
        ${deckKeys.has(vocabKey(entry)) ? `<span class="in-deck">✓ In deck</span>` : `<button class="button small" data-add="vocab:${vocabIndex}" data-question="${index}">+ Deck</button>`}
      </div>
    </div>`).join("");

  const grammarRows = (question.grammar || []).map((entry, grammarIndex) => `
    <div class="vocab-item grammar-item">
      <div class="vocab-word"><span class="vocab-kanji ja grammar-pattern">${escapeHtml(entry.pattern)}</span></div>
      <div class="vocab-body">
        <p><strong>${escapeHtml(entry.meaning)}</strong></p>
        <p class="formation">${escapeHtml(entry.formation)}</p>
        ${entry.note ? `<p class="muted small">${escapeHtml(entry.note)}</p>` : ""}
        <p class="example ja">${renderJa(entry.example)}</p>
        <p class="example-en">${escapeHtml(entry.example_translation)}</p>
      </div>
      <div class="vocab-action">
        ${deckKeys.has(grammarKey(entry)) ? `<span class="in-deck">✓ In deck</span>` : `<button class="button small" data-add="grammar:${grammarIndex}" data-question="${index}">+ Deck</button>`}
      </div>
    </div>`).join("");

  const missingVocab = question.vocab.filter((entry) => !deckKeys.has(vocabKey(entry))).length;

  return `
    <article class="card review-card ${question.correct ? "is-correct" : "is-wrong"}" id="q${index}">
      <header class="question-head">
        <span class="badge">${meta.ja}</span>
        <span class="muted">${meta.en} · Question ${index + 1}</span>
        <span class="result ${question.correct ? "good" : "bad"}">${question.correct ? "Correct" : question.chosen == null ? "Not answered" : "Wrong"}</span>
      </header>
      ${passage}
      ${stem}
      <p class="translation">${escapeHtml(question.translation)}</p>
      ${completed}
      <h3>Why</h3>
      <p class="explanation">${escapeHtml(question.explanation)}</p>
      <h3>Choices</h3>
      <ol class="review-choices">${choices}</ol>
      <div class="subhead">
        <h3>Vocabulary</h3>
        ${missingVocab > 1 ? `<button class="button small ghost" data-add-question="${index}">+ Add all ${missingVocab} to deck</button>` : ""}
      </div>
      <div class="vocab-list">${vocabRows}</div>
      ${grammarRows ? `<h3>Grammar</h3><div class="vocab-list">${grammarRows}</div>` : ""}
    </article>`;
}

// --- deck ----------------------------------------------------------------

async function viewDeck() {
  const [cards, settings] = await Promise.all([api("GET", "/api/cards"), api("GET", "/api/settings")]);
  let query = "";
  let kind = "all";
  let expanded = null;

  app.innerHTML = `
    <section class="card">
      <div class="deck-head">
        <div>
          <h1>Your deck</h1>
          <p class="muted">Words and grammar you added from reviews. Memory is the predicted chance you'd recall it right now.</p>
        </div>
        <a class="button primary" href="#/study">Study now</a>
      </div>
      <div class="deck-filters">
        <input type="search" class="search" placeholder="Search word, reading or meaning…" aria-label="Search deck">
        <div class="segmented">
          <button class="active" data-kind="all">All</button>
          <button data-kind="vocab">Vocab</button>
          <button data-kind="grammar">Grammar</button>
        </div>
      </div>
      <div class="deck-table-wrap"></div>
    </section>
    <section class="card settings-card">
      <h2>Review settings</h2>
      <div class="settings-grid">
        <label>
          <span>New cards per day</span>
          <input type="number" min="0" max="200" step="1" data-setting="new_cards_per_day" value="${settings.new_cards_per_day}">
        </label>
        <label>
          <span>Target recall</span>
          <select data-setting="desired_retention">
            ${[0.8, 0.85, 0.9, 0.95].map((value) => `<option value="${value}" ${Number(settings.desired_retention) === value ? "selected" : ""}>${Math.round(value * 100)}%${value === 0.9 ? " (recommended)" : ""}</option>`).join("")}
          </select>
        </label>
      </div>
      <p class="muted small">Cards come back when your predicted recall drops to the target. A higher target means more frequent reviews.</p>
    </section>`;

  const wrap = app.querySelector(".deck-table-wrap");
  for (const input of app.querySelectorAll("[data-setting]")) {
    input.addEventListener("change", async () => {
      const value = input.dataset.setting === "desired_retention" ? Number(input.value) : Math.round(Number(input.value));
      try {
        await api("PATCH", "/api/settings", { [input.dataset.setting]: value });
        toast("Settings saved");
      } catch (error) {
        toast(error.message);
      }
    });
  }

  const render = () => {
    const needle = query.trim().toLowerCase();
    const visible = cards.filter((card) => {
      if (kind !== "all" && card.kind !== kind) return false;
      if (!needle) return true;
      return Object.values(card.data).join(" ").toLowerCase().includes(needle);
    });
    if (!cards.length) {
      wrap.innerHTML = `<p class="empty">Your deck is empty. After a mini test, press <strong>+ Deck</strong> next to words you don't know.</p>`;
      return;
    }
    wrap.innerHTML = `
      <table class="deck-table">
        <thead><tr><th>Word</th><th>Meaning</th><th>Status</th><th>Memory</th><th>Next review</th><th></th></tr></thead>
        <tbody>
          ${visible.map((card) => {
            const front = card.kind === "vocab" ? card.data.word : card.data.pattern;
            const reading = card.kind === "vocab" ? card.data.reading : "grammar";
            const memory = card.retrievability == null ? null : Math.round(card.retrievability * 100);
            return `
              <tr data-card="${card.id}" class="${expanded === card.id ? "expanded" : ""}">
                <td><span class="ja deck-word">${escapeHtml(front)}</span><span class="muted small deck-reading">${escapeHtml(reading)}</span></td>
                <td class="deck-meaning">${escapeHtml(card.data.meaning)}</td>
                <td><span class="state state-${card.state}">${STATE_NAMES[card.state]}</span></td>
                <td>${memory == null ? `<span class="muted">-</span>` : `<div class="memory"><div class="meter"><span style="width:${memory}%" class="${memory < 70 ? "low" : ""}"></span></div><span>${memory}%</span></div>`}</td>
                <td class="muted">${card.state === "new" ? "new" : formatDue(card.due)}</td>
                <td><button class="icon-button" data-delete="${card.id}" title="Remove from deck" aria-label="Remove from deck">${CLOSE_ICON}</button></td>
              </tr>
              ${expanded === card.id ? `
                <tr class="detail-row"><td colspan="6">
                  ${card.kind === "grammar" ? `<p class="formation">${escapeHtml(card.data.formation || "")}</p>` : `<p><span class="pos">${escapeHtml(card.data.pos || "")}</span></p>`}
                  <p class="example ja">${renderJa(card.data.example || "")}</p>
                  <p class="example-en">${escapeHtml(card.data.example_translation || "")}</p>
                  <p class="muted small">Reviewed ${card.reps} time${card.reps === 1 ? "" : "s"} · forgotten ${card.lapses} time${card.lapses === 1 ? "" : "s"}${card.stability ? ` · stability ${card.stability.toFixed(1)} days` : ""}</p>
                </td></tr>` : ""}`;
          }).join("")}
        </tbody>
      </table>
      <p class="muted small">${visible.length} of ${cards.length} cards</p>`;
  };

  app.querySelector(".search").addEventListener("input", (event) => {
    query = event.target.value;
    render();
  });
  app.querySelector(".segmented").addEventListener("click", (event) => {
    const button = event.target.closest("[data-kind]");
    if (!button) return;
    kind = button.dataset.kind;
    for (const other of app.querySelectorAll("[data-kind]")) other.classList.toggle("active", other === button);
    render();
  });
  wrap.addEventListener("click", async (event) => {
    const remove = event.target.closest("[data-delete]");
    if (remove) {
      const card = cards.find((item) => item.id === Number(remove.dataset.delete));
      if (!confirm(`Remove ${card.kind === "vocab" ? card.data.word : card.data.pattern} from your deck? Its review history is deleted too.`)) return;
      await api("DELETE", `/api/cards/${card.id}`);
      cards.splice(cards.indexOf(card), 1);
      render();
      return;
    }
    const row = event.target.closest("[data-card]");
    if (row) {
      expanded = expanded === Number(row.dataset.card) ? null : Number(row.dataset.card);
      render();
    }
  });
  render();
}

// --- study ---------------------------------------------------------------

async function viewStudy() {
  const queue = await api("GET", "/api/study");
  const main = queue.cards.filter((card) => card.state === "review" || card.state === "new");
  const learning = queue.cards
    .filter((card) => card.state === "learning" || card.state === "relearning")
    .map((card) => ({ card, dueAt: new Date(card.due).getTime() }));
  let current = null;
  let revealed = false;
  let reviewed = 0;

  const pickNext = () => {
    learning.sort((left, right) => left.dueAt - right.dueAt);
    if (learning.length && learning[0].dueAt <= Date.now()) return learning.shift().card;
    if (main.length) return main.shift();
    if (learning.length) return learning.shift().card;
    return null;
  };

  const counts = () => {
    const all = [...main, ...learning.map((entry) => entry.card), ...(current ? [current] : [])];
    return {
      new: all.filter((card) => card.state === "new").length,
      learning: all.filter((card) => card.state === "learning" || card.state === "relearning").length,
      review: all.filter((card) => card.state === "review").length,
    };
  };

  const render = () => {
    if (!current) {
      app.innerHTML = `
        <section class="card study-done">
          <h1>${reviewed ? "Session complete 🎉" : "Nothing to study right now"}</h1>
          <p class="lead">${reviewed ? `You reviewed ${reviewed} card${reviewed === 1 ? "" : "s"}.` : queue.new_total ? "You've reached today's new-card limit. Come back tomorrow." : "Add words to your deck from a test review, then come back here."}</p>
          <div class="actions center"><a class="button primary" href="#/">Back to Today</a><a class="button ghost" href="#/deck">Open deck</a></div>
        </section>`;
      return;
    }
    const remaining = counts();
    const data = current.data;
    const isVocab = current.kind === "vocab";
    const front = isVocab ? data.word : data.pattern;
    app.innerHTML = `
      <section class="study-shell">
        <div class="study-counts">
          <span class="count new" title="New">${remaining.new} new</span>
          <span class="count learning" title="Learning">${remaining.learning} learning</span>
          <span class="count review" title="Review">${remaining.review} review</span>
        </div>
        <article class="card flashcard ${revealed ? "revealed" : ""}">
          <span class="badge">${isVocab ? "Vocabulary" : "Grammar"}${current.state === "new" ? " · new" : ""}</span>
          <p class="flash-front ja">${escapeHtml(front)}</p>
          ${revealed ? `
            <div class="flash-back">
              ${isVocab ? `<p class="flash-reading ja">${escapeHtml(data.reading)} ${speakButton(data.word)}</p>` : ""}
              <p class="flash-meaning">${escapeHtml(data.meaning)}</p>
              ${isVocab && data.pos ? `<p class="pos">${escapeHtml(data.pos)}</p>` : ""}
              ${!isVocab && data.formation ? `<p class="formation">${escapeHtml(data.formation)}</p>` : ""}
              ${data.example ? `<p class="example ja big-ja">${renderJa(data.example)}</p><p class="example-en">${escapeHtml(data.example_translation || "")}</p>` : ""}
            </div>` : ""}
        </article>
        <div class="study-actions">
          ${revealed ? Object.entries(RATING_NAMES).map(([rating, name]) => `
            <button class="rate rate-${rating}" data-rate="${rating}">
              <span class="rate-name">${name}</span>
              <span class="rate-interval">${formatInterval(current.intervals[rating])}</span>
              <span class="rate-key">${rating}</span>
            </button>`).join("") : `<button class="button primary wide" data-reveal>Show answer <span class="rate-key">Space</span></button>`}
        </div>
      </section>`;
  };

  const reveal = () => {
    if (!current || revealed) return;
    revealed = true;
    render();
  };

  const rate = async (rating) => {
    if (!current || !revealed || rate.busy) return;
    rate.busy = true;
    try {
      const updated = await api("POST", `/api/cards/${current.id}/review`, { rating });
      reviewed += 1;
      const dueAt = new Date(updated.due).getTime();
      if (dueAt - Date.now() <= LEARN_AHEAD_MS) learning.push({ card: updated, dueAt });
      current = pickNext();
      revealed = false;
      render();
    } finally {
      rate.busy = false;
    }
  };

  const onClick = (event) => {
    if (event.target.closest("[data-reveal]")) reveal();
    const rateButton = event.target.closest("[data-rate]");
    if (rateButton) rate(Number(rateButton.dataset.rate));
  };
  const onKey = (event) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      reveal();
    } else if (["1", "2", "3", "4"].includes(event.key)) {
      rate(Number(event.key));
    }
  };
  app.addEventListener("click", onClick);
  document.addEventListener("keydown", onKey);
  cleanupView = () => {
    app.removeEventListener("click", onClick);
    document.removeEventListener("keydown", onKey);
  };

  current = pickNext();
  render();
}

// --- history -------------------------------------------------------------

async function viewHistory() {
  const tests = (await api("GET", "/api/tests")).filter((test) => test.submitted_at);
  app.innerHTML = `
    <section class="card">
      <h1>History</h1>
      ${tests.length ? `
        <table class="history-table">
          <thead><tr><th>Date</th><th>Questions</th><th>Score</th><th>Time</th><th></th></tr></thead>
          <tbody>
            ${tests.map((test) => `
              <tr>
                <td>${formatDate(test.local_date)}</td>
                <td>${test.size}</td>
                <td><div class="memory"><div class="meter"><span style="width:${percent(test.score, test.size)}%"></span></div><span>${test.score} / ${test.size}</span></div></td>
                <td class="muted">${formatDuration(test.seconds)}</td>
                <td><a class="button small ghost" href="#/review/${test.id}">Review</a></td>
              </tr>`).join("")}
          </tbody>
        </table>` : `<p class="empty">No finished tests yet. <a href="#/">Take today's mini test</a>.</p>`}
    </section>`;
}
