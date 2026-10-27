// Renders question-bank markup to HTML.
//   漢字{かんじ}  ruby over the kanji run before the braces
//   [[...]]       underlined target
//   {{1}}..{{4}}  answer slots (sentence building)

const KANJI_RUN_AT_END = /[㐀-䶿一-鿿豈-﫿々〆ヶ]+$/;
const TOKEN = /\[\[|\]\]|\{\{(\d)\}\}|\{([^{}]*)\}/g;

export function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// options.slot(number) returns HTML for answer slot `number` (1-4).
export function renderJa(text, options = {}) {
  const source = String(text ?? "");
  const pieces = [];
  let pending = "";
  let lastIndex = 0;
  const flush = (plain) => pieces.push(escapeHtml(plain));

  for (const match of source.matchAll(TOKEN)) {
    pending += source.slice(lastIndex, match.index);
    lastIndex = match.index + match[0].length;

    if (match[2] !== undefined) {
      const run = pending.match(KANJI_RUN_AT_END);
      if (!run) {
        pending += match[0];
        continue;
      }
      flush(pending.slice(0, run.index));
      pieces.push(`<ruby>${escapeHtml(run[0])}<rt>${escapeHtml(match[2])}</rt></ruby>`);
      pending = "";
      continue;
    }

    flush(pending);
    pending = "";
    if (match[0] === "[[") pieces.push('<span class="target">');
    else if (match[0] === "]]") pieces.push("</span>");
    else pieces.push(options.slot ? options.slot(Number(match[1])) : "＿＿");
  }
  flush(pending + source.slice(lastIndex));
  return pieces.join("");
}

export function plainJa(text) {
  return String(text ?? "")
    .replace(/\[\[|\]\]/g, "")
    .replace(/\{\{\d\}\}/g, "＿＿")
    .replace(/\{[^{}]*\}/g, "");
}
