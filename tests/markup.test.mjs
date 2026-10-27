import assert from "node:assert/strict";
import { test } from "node:test";

import { plainJa, renderJa } from "../static/markup.js";

test("puts furigana over the kanji run only", () => {
  assert.equal(renderJa("考{かんが}える"), "<ruby>考<rt>かんが</rt></ruby>える");
  assert.equal(
    renderJa("日本語{にほんご}を勉強{べんきょう}"),
    "<ruby>日本語<rt>にほんご</rt></ruby>を<ruby>勉強<rt>べんきょう</rt></ruby>",
  );
  assert.equal(renderJa("時々{ときどき}"), "<ruby>時々<rt>ときどき</rt></ruby>");
});

test("underlines targets, including furigana inside them", () => {
  assert.equal(renderJa("[[慎重]]に"), '<span class="target">慎重</span>に');
  assert.equal(renderJa("[[見直{みなお}す]]"), '<span class="target"><ruby>見直<rt>みなお</rt></ruby>す</span>');
});

test("renders answer slots", () => {
  const html = renderJa("A {{1}} {{2}}", { slot: (number) => `<i>${number}</i>` });
  assert.equal(html, "A <i>1</i> <i>2</i>");
  assert.equal(renderJa("{{3}}"), "＿＿");
});

test("escapes HTML", () => {
  assert.equal(renderJa("<b>漢{かん}</b>"), "&lt;b&gt;<ruby>漢<rt>かん</rt></ruby>&lt;/b&gt;");
});

test("plain text strips all markup", () => {
  assert.equal(plainJa("[[慎重]]に考{かんが}える{{1}}"), "慎重に考える＿＿");
});
