import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";

import {
  STEPS,
  parseArgs,
  pauseAfter,
  selectSteps,
} from "./console-demo-playwright.mjs";

test("step ids are unique and every step carries narration", () => {
  assert.equal(new Set(STEPS.map((step) => step.id)).size, STEPS.length);
  for (const step of STEPS) {
    assert.match(step.presenterNotes, /\S/);
    assert.equal(typeof step.action, "function");
  }
});

test("resume selection is inclusive and rejects unknown ids", () => {
  assert.equal(selectSteps("complete-dual-control")[0].id, "complete-dual-control");
  assert.throws(() => selectSteps("missing"), /unknown step id/);
});

test("argument parser supports unattended screenshot capture", () => {
  assert.deepEqual(
    parseArgs(["--from", "submit-review", "--no-pause", "--headless", "--slow-mo", "25"]),
    {
      list: false,
      from: "submit-review",
      noPause: true,
      headless: true,
      screenshots: "",
      slowMo: 25,
    },
  );
});

test("unattended mode never reads stdin", async () => {
  const input = new PassThrough();
  let reads = 0;
  input.on("data", () => {
    reads += 1;
  });
  await pauseAfter({ noPause: true }, input, new PassThrough());
  assert.equal(reads, 0);
});
