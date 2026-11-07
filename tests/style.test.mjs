import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../static/style.css", import.meta.url), "utf8");
const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
const COLOR_LITERAL = /#[0-9a-f]{3,8}\b|\b(?:rgb|hsl)a?\(|:\s*(?:white|black)\b/i;
const LIGHT_BLOCK = /^:root \{\r?\n([\s\S]*?)^\}/m;
const DARK_BLOCK = /^:root\[data-theme="dark"\] \{\r?\n([\s\S]*?)^\}/m;

function declarations(block) {
  const withoutComments = block.replace(/\/\*[\s\S]*?\*\//g, "");
  return new Map([...withoutComments.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]));
}

const light = declarations(css.match(LIGHT_BLOCK)[1]);
const dark = declarations(css.match(DARK_BLOCK)[1]);

test("colors appear only in the light and dark theme blocks", () => {
  const rest = css.replace(LIGHT_BLOCK, "").replace(DARK_BLOCK, "").replace(/\/\*[\s\S]*?\*\//g, "");
  const offending = rest.split("\n").filter((line) => COLOR_LITERAL.test(line));
  assert.deepEqual(offending, [], "use a theme variable instead of a literal color");
});

test("the dark theme overrides every color variable and nothing else", () => {
  const colorVariables = [...light].filter(([, value]) => COLOR_LITERAL.test(value)).map(([name]) => name);
  assert.deepEqual(colorVariables.filter((name) => !dark.has(name)), [], "missing from the dark theme");
  assert.deepEqual([...dark.keys()].filter((name) => !light.has(name)), [], "dark-only variables");
});

test("every variable the stylesheet uses is defined", () => {
  const used = new Set([...css.matchAll(/var\((--[\w-]+)/g)].map((match) => match[1]));
  assert.deepEqual([...used].filter((name) => !light.has(name)), []);
});

test("the theme is applied before the stylesheet loads, so the page never flashes", () => {
  const themeScript = html.indexOf('<script src="/theme.js"></script>');
  assert.ok(themeScript !== -1, "theme.js must be a classic blocking script (no module, defer or async)");
  assert.ok(themeScript < html.indexOf('<link rel="stylesheet"'), "theme.js must load before style.css");
});
