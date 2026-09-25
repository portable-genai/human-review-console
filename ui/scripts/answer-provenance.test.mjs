/**
 * The model pills' source: what answered, read off the console's own service responses.
 *
 * These import `lib/answer-provenance.mjs` itself, so a rule that changes in the component
 * changes here too. What is checked is that a pill can never name a model no response named,
 * that another origin's response cannot set it, and that the one `fetch` wrapper is installed
 * once and put back.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { answerOf, isConsoleApi, watchAnswers } from "../lib/answer-provenance.mjs";

const HERE = "http://console.test/";
// This console calls its service cross-origin, at the base `lib/api-base.mjs` resolves.
const BASE = "http://localhost:8087";

function reply(headers) {
  return { headers: new Headers(headers) };
}

function host(headers) {
  const calls = [];
  const original = async (input) => {
    calls.push(input);
    return reply(headers);
  };
  return { fetch: original, original, calls, location: { href: HERE } };
}

test("a response that names no model is no answer, never a guess", () => {
  assert.equal(answerOf(new Headers()), null);
  assert.equal(answerOf(new Headers({ "x-search-used": "true" })), null);
  assert.equal(answerOf(new Headers({ "x-answered-by": "  " })), null);
});

test("the answering model and the search flag are read as sent", () => {
  assert.deepEqual(answerOf(new Headers({ "x-answered-by": "gemini-3.5-flash" })), {
    model: "gemini-3.5-flash",
    search: false,
  });
  assert.deepEqual(
    answerOf(new Headers({ "x-answered-by": "a, b", "x-search-used": "true" })),
    { model: "a, b", search: true },
  );
});

test("only the service base this console calls counts", () => {
  assert.equal(isConsoleApi(`${BASE}/v1/reviews`, HERE, BASE), true);
  assert.equal(isConsoleApi(new URL(`${BASE}/healthz`), HERE, BASE), true);
  assert.equal(isConsoleApi({ url: `${BASE}/v1/reviews/x` }, HERE, BASE), true);
  assert.equal(isConsoleApi("http://elsewhere.test/v1/reviews", HERE, BASE), false);
  assert.equal(isConsoleApi("http://localhost:9999/v1/reviews", HERE, BASE), false);
  assert.equal(isConsoleApi("/static/app.js", HERE, BASE), false);
  assert.equal(isConsoleApi(42, HERE, BASE), false);
  // A base with a path prefix admits only that prefix.
  const prefixed = "http://svc.test/review";
  assert.equal(isConsoleApi("http://svc.test/review/v1/reviews", HERE, prefixed), true);
  assert.equal(isConsoleApi("http://svc.test/reviewer/v1", HERE, prefixed), false);
});

test("the wrapper reports an answer from the service and ignores other origins", async () => {
  const window = host({ "x-answered-by": "model-a", "x-search-used": "true" });
  const seen = [];
  const stop = watchAnswers(window, BASE, (answer) => seen.push(answer));
  await window.fetch(`${BASE}/v1/reviews`, { method: "POST" });
  await window.fetch("http://elsewhere.test/v1/reviews");
  stop();
  assert.deepEqual(seen, [{ model: "model-a", search: true }]);
  assert.equal(window.calls.length, 2, "the wrapper must still perform every call");
});

test("the wrapper is installed once however many listeners, and restored by the last", async () => {
  const window = host({ "x-answered-by": "model-b" });
  const first = [];
  const second = [];
  const stopFirst = watchAnswers(window, BASE, (answer) => first.push(answer.model));
  const wrapped = window.fetch;
  const stopSecond = watchAnswers(window, BASE, (answer) => second.push(answer.model));
  assert.equal(window.fetch, wrapped, "a second listener wrapped fetch again");
  await window.fetch(`${BASE}/v1/reviews`);
  stopFirst();
  assert.equal(window.fetch, wrapped, "the wrapper left while a listener remained");
  stopSecond();
  assert.equal(window.fetch, window.original, "the original fetch was not put back");
  assert.deepEqual(first, ["model-b"]);
  assert.deepEqual(second, ["model-b"]);
});
