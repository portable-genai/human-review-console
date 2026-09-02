// The interface tier's three-state guard: the JavaScript twin of the Python scanner.
//
// The Python scanner in `tests/unit/test_three_state_env_reads.py` walks `src`, `scripts` and
// `eval`. It cannot walk `ui/`, so this repository shipped a two-state read of REVIEW_PROFILE in
// `next.config.mjs` while its Python tier was fully three-state and green. One tier having a
// scanner is not the same as the repository having one.
//
// Two halves, and both are needed. The behaviour tests pin what `envread.mjs` does with each of
// the three states. The SCAN walks every shipped file under `ui/` and fails the build on a
// `process.env.X || default` (or `?? default`, or a destructured default) that can widen anything.
//
// The scan was proved red before it was believed: with the previous `next.config.mjs` line
// restored it reports that exact line, which is the only reason its green counts for anything.

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { envSetting, settingOrDefault } from "../lib/envread.mjs";

const UI_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCANNED_EXTENSIONS = [".mjs", ".js", ".ts", ".tsx"];
const SKIPPED_DIRECTORIES = new Set(["node_modules", ".next", "out", "coverage", "dist"]);

//: variable name -> why a two-state read of it is not a posture decision. Adding an entry is a
//: reviewable claim, not a way past the test: if the variable can widen access, relax a check,
//: name a host, an origin, an audience or a profile, it does not belong here.
const TWO_STATE_READS_WITH_A_REASON = {
  NEXT_PUBLIC_BASE_PATH:
    "the reverse-proxy sub-path the console mounts under. Unset and emptied MUST mean the same " +
    "thing (mount at the root), because a base path names a location and not a permission: it " +
    "grants nothing, relaxes nothing, and an emptied value cannot widen what the console serves.",
  NODE_ENV:
    "set by the toolchain, never by an operator, and compared against the exact literal " +
    "'production'. Unset and emptied both land on the DEV branch, which is the closed direction " +
    "here: dev adds no allowance, it only declines to assert production-only headers.",
  PYTHON:
    "names the interpreter a DEMO script spawns. It is not shipped in the console bundle, grants " +
    "nothing to a browser, and an emptied value falls through to the documented discovery order.",
  CHROME_PATH:
    "names the browser binary a DEMO script launches, the same class as PYTHON above. It is not " +
    "shipped in the console bundle and grants nothing to a browser: it selects which local " +
    "executable Playwright drives, and both unset and emptied fall through to Playwright's own " +
    "downloaded browser, which is the same behaviour rather than a more permissive one.",
};

// This file itself. It carries DELIBERATE two-state samples, in the red-proof test below, so
// scanning it would report its own fixtures forever. It ships in no bundle and serves no request.
const SELF = fileURLToPath(import.meta.url);

/** Every shipped file under `ui/`, excluding build output, dependencies and this file. */
function scannedFiles(directory = UI_ROOT) {
  const out = [];
  for (const entry of readdirSync(directory)) {
    if (SKIPPED_DIRECTORIES.has(entry) || entry.startsWith(".")) continue;
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      out.push(...scannedFiles(path));
    } else if (SCANNED_EXTENSIONS.some((ext) => entry.endsWith(ext)) && path !== SELF) {
      out.push(path);
    }
  }
  return out.sort();
}

// A line whose code has been commented out entirely. Prose ABOUT a two-state read (this file and
// `envread.mjs` are both full of it) is not a two-state read, and a scanner that cannot tell them
// apart makes documenting the defect impossible. Only whole-line comments are skipped: a trailing
// `// ...` after real code leaves the code itself on the line and still matches.
const COMMENT_LINE = /^\s*(\/\/|\*|\/\*)/;

// `process.env.X || "d"`, `process.env.X ?? "d"`, and the optional-chained `?.replace(...) || "d"`
// form the API client used. Anything supplying a fallback for an absent value is a two-state read.
const TWO_STATE_READ =
  /process\.env\.([A-Z_][A-Z0-9_]*)\s*(?:\?\.[^|?]*)?(?:\|\||\?\?)\s*(?!$)/g;

/** @returns {{file: string, line: number, variable: string, text: string}[]} */
function twoStateReads() {
  const findings = [];
  for (const file of scannedFiles()) {
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((text, index) => {
      if (COMMENT_LINE.test(text)) return;
      for (const match of text.matchAll(TWO_STATE_READ)) {
        const variable = match[1];
        if (variable in TWO_STATE_READS_WITH_A_REASON) continue;
        findings.push({
          file: relative(UI_ROOT, file),
          line: index + 1,
          variable,
          text: text.trim(),
        });
      }
    });
  }
  return findings;
}

test("an unset variable takes the reviewed default", () => {
  const setting = envSetting(undefined, "REVIEW_PROFILE");
  assert.equal(setting.isUnset, true);
  assert.equal(setting.isConfiguredEmpty, false);
  assert.equal(setting.hasValue, false);
  assert.equal(settingOrDefault(undefined, "REVIEW_PROFILE", "local"), "local");
});

test("a variable set to a real value is used", () => {
  const setting = envSetting("gcp", "REVIEW_PROFILE");
  assert.equal(setting.hasValue, true);
  assert.equal(settingOrDefault("gcp", "REVIEW_PROFILE", "local"), "gcp");
});

test("an EMPTIED variable refuses rather than inheriting the unset default", () => {
  // The exact defect: `(process.env.REVIEW_PROFILE || "local") !== "local"` resolved this to
  // the demo posture and dropped Strict-Transport-Security.
  assert.equal(envSetting("", "REVIEW_PROFILE").isConfiguredEmpty, true);
  assert.throws(() => settingOrDefault("", "REVIEW_PROFILE", "local"), /set to an empty value/);
});

test("a whitespace-only variable is emptied, not valued", () => {
  assert.equal(envSetting("   ", "REVIEW_PROFILE").isConfiguredEmpty, true);
  assert.throws(() => settingOrDefault("  ", "REVIEW_PROFILE", "local"), /empty value/);
});

test("no shipped file under ui/ resolves a security-relevant variable in two states", () => {
  const findings = twoStateReads();
  const report = findings
    .map((f) => `  ${f.file}:${f.line}  ${f.variable}\n      ${f.text}`)
    .join("\n");
  assert.equal(
    findings.length,
    0,
    `two-state environment reads in the interface tier:\n${report}\n\n` +
      "Use settingOrDefault(process.env.X, \"X\", <default>) from lib/envread.mjs, or add the " +
      "variable to TWO_STATE_READS_WITH_A_REASON with a reason that survives review.",
  );
});

test("the scan can actually find a two-state read", () => {
  // A checker never observed red is indistinguishable from one that asserts nothing. This proves
  // the pattern matches the real defect, in the exact shape next.config.mjs must never carry.
  const planted = 'const secure = (process.env.REVIEW_PROFILE || "local") !== "local";';
  const matches = [...planted.matchAll(TWO_STATE_READ)].map((m) => m[1]);
  assert.deepEqual(matches, ["REVIEW_PROFILE"]);
  const nullish = "const api = process.env.NEXT_PUBLIC_REVIEW_API_URL ?? \"http://localhost:8087\";";
  assert.deepEqual(
    [...nullish.matchAll(TWO_STATE_READ)].map((m) => m[1]),
    ["NEXT_PUBLIC_REVIEW_API_URL"],
  );
  const chained = 'const b = process.env.NEXT_PUBLIC_REVIEW_API_URL?.replace(/\\/$/, "") || "x";';
  assert.deepEqual(
    [...chained.matchAll(TWO_STATE_READ)].map((m) => m[1]),
    ["NEXT_PUBLIC_REVIEW_API_URL"],
  );
});
