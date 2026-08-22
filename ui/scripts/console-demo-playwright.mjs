#!/usr/bin/env node

import { spawn } from "node:child_process";
import { once } from "node:events";
import { createConnection } from "node:net";
import { createInterface } from "node:readline/promises";
import { existsSync, mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const UI_DIR = resolve(SCRIPT_DIR, "..");
const ROOT_DIR = resolve(UI_DIR, "..");
const API_URL = "http://127.0.0.1:18087";
const UI_URL = "http://127.0.0.1:13007";

export function parseArgs(argv) {
  const options = {
    list: false,
    from: "",
    noPause: false,
    headless: false,
    screenshots: "",
    slowMo: 0,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--list") options.list = true;
    else if (arg === "--no-pause") options.noPause = true;
    else if (arg === "--headless") options.headless = true;
    else if (arg === "--from") options.from = argv[++index] || "";
    else if (arg === "--screenshots") options.screenshots = argv[++index] || "";
    else if (arg === "--slow-mo") options.slowMo = Number(argv[++index] || "0");
    else throw new Error(`unknown option: ${arg}`);
  }
  if (!Number.isFinite(options.slowMo) || options.slowMo < 0) {
    throw new Error("--slow-mo must be a non-negative number");
  }
  return options;
}

async function choosePersona(page, id) {
  const picker = page.getByLabel("Acting reviewer:");
  await picker.selectOption(id);
  await page.getByText(`acting as ${id}`).waitFor();
}

async function seedReview() {
  const response = await fetch(`${API_URL}/v1/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Dev-Persona": "analyst" },
    body: JSON.stringify({
      action: "disburse_facility",
      subject: "Acme Holdings Pte Ltd (FICTIONAL)",
      summary: "Disburse SGD 2.5m revolving facility.",
      severity: "high",
      sod_group: "group:origination",
      citations: [
        {
          source_id: "facility-demo-001",
          title: "Approved facility record (FICTIONAL)",
          snippet: "Independent approval is required.",
        },
      ],
    }),
  });
  if (!response.ok) throw new Error(`demo fixture submission failed: ${response.status}`);
  return response.json();
}

async function pendingReview(persona = "analyst") {
  const response = await fetch(`${API_URL}/v1/reviews`, {
    headers: { "X-Dev-Persona": persona },
  });
  if (!response.ok) throw new Error(`queue lookup failed: ${response.status}`);
  const queue = await response.json();
  return queue[0] || null;
}

async function ensureReview() {
  return (await pendingReview()) || seedReview();
}

async function ensureFirstApproval() {
  const item = await ensureReview();
  if (item.approvals_count > 0) return item;
  const response = await fetch(`${API_URL}/v1/reviews/${item.review_id}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Dev-Persona": "approver" },
    body: JSON.stringify({
      disposition: "approve",
      reason: "First independent review completed.",
    }),
  });
  if (!response.ok) throw new Error(`first approval setup failed: ${response.status}`);
  return response.json();
}

async function openConsole(page) {
  await page.goto(UI_URL);
  await page.getByRole("heading", { name: "Human-Review Console" }).waitFor();
  await page.getByText("profile: local").waitFor();
}

export const STEPS = [
  {
    id: "open-console",
    title: "Open the governed review queue",
    presenterNotes:
      "A risk operations analyst opens the shared review queue to see decisions that require accountable human action. The console establishes the active deployment profile and tenant context before it reveals any pending work, giving the reviewer a clear boundary for every action that follows.",
    action: async (page) => {
      await openConsole(page);
      await page.getByTestId("review-queue").waitFor();
    },
  },
  {
    id: "submit-review",
    title: "Submit a high-severity action",
    presenterNotes:
      "The analyst submits a high-severity facility action because policy requires dual control before the underlying process may continue. The live queue shows the action, its maker, severity, approval count, producer evidence, and the exact next action, so a reviewer can verify why the item is waiting.",
    action: async (page) => {
      await openConsole(page);
      await choosePersona(page, "analyst");
      if ((await page.getByTestId("review-item").count()) === 0) {
        await page.getByRole("button", { name: "+ submit demo item" }).click();
      }
      const item = page.getByTestId("review-item").first();
      await item.waitFor();
      await item.click();
      await page.getByTestId("review-evidence").waitFor();
      await page.getByText("Collect 2 more independent approval(s)").waitFor();
    },
  },
  {
    id: "deny-self-approval",
    title: "Refuse a maker self-approval",
    presenterNotes:
      "The same analyst attempts to approve their own submission, and the four-eyes control refuses the action. The refusal is visible as a specific governance finding while the queue item remains pending, proving that the control fails closed and does not turn an invalid attempt into an approval.",
    action: async (page) => {
      await ensureReview();
      await openConsole(page);
      await choosePersona(page, "analyst");
      await page.getByTestId("review-item").first().click();
      await page.getByLabel("Reason for your decision").fill("Maker attempted self approval.");
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await page.getByTestId("operation-result").getByText(/refused: self_approval/).waitFor();
      await page.getByText(/Pending queue \(1\)/).waitFor();
    },
  },
  {
    id: "first-independent-approval",
    title: "Record the first independent check",
    presenterNotes:
      "An independent approver reviews the same evidence and records the first valid approval. The item remains pending at one of two checks, making the dual-control calculation visible and preventing one successful review from being mistaken for final authorization.",
    action: async (page) => {
      await ensureReview();
      await openConsole(page);
      await choosePersona(page, "approver");
      await page.getByTestId("review-item").first().click();
      await page.getByLabel("Reason for your decision").fill("Within delegated authority.");
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await page.getByTestId("operation-result").getByText(/approve recorded -> pending/).waitFor();
      await page.getByText(/Pending queue \(1\)/).waitFor();
    },
  },
  {
    id: "complete-dual-control",
    title: "Complete dual control",
    presenterNotes:
      "A second independent approver supplies the remaining check, completing dual control with a distinct verified identity. The item leaves the pending queue only after the second valid approval, while the completed checks and decision evidence remain attached to the governed outcome for audit.",
    action: async (page) => {
      await ensureFirstApproval();
      await openConsole(page);
      await choosePersona(page, "second-approver");
      await page.getByTestId("review-item").first().click();
      await page.getByLabel("Reason for your decision").fill("Second independent review complete.");
      await page.getByRole("button", { name: "Approve", exact: true }).click();
      await page.getByTestId("operation-result").getByText(/approve recorded -> approved/).waitFor();
      await page.getByText(/Pending queue \(0\)/).waitFor();
    },
  },
  {
    id: "prove-tenant-boundary",
    title: "Prove the tenant boundary",
    presenterNotes:
      "A user from another institution opens the same console channel and receives an empty queue. The server derives tenant scope from the verified persona rather than trusting a browser field, so changing the user interface context cannot expose another institution's review records.",
    action: async (page) => {
      await ensureReview();
      await openConsole(page);
      await choosePersona(page, "other-tenant");
      await page.getByText(/Pending queue \(0\)/).waitFor();
      await page.getByText("Nothing pending for this tenant.").waitFor();
    },
  },
];

export function selectSteps(fromId) {
  if (!fromId) return STEPS;
  const index = STEPS.findIndex((step) => step.id === fromId);
  if (index < 0) throw new Error(`unknown step id: ${fromId}`);
  return STEPS.slice(index);
}

export async function pauseAfter(options, input = process.stdin, output = process.stdout) {
  if (options.noPause) return;
  const prompt = createInterface({ input, output });
  try {
    await prompt.question("Enter for next step...");
  } finally {
    prompt.close();
  }
}

function captureOutput(child, label) {
  const lines = [];
  for (const stream of [child.stdout, child.stderr]) {
    stream?.on("data", (chunk) => {
      lines.push(...String(chunk).split("\n").filter(Boolean).map((line) => `${label}: ${line}`));
      if (lines.length > 80) lines.splice(0, lines.length - 80);
    });
  }
  return () => lines.join("\n");
}

async function waitForReady(url, child, logs, label) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${label} exited before readiness\n${logs()}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Service has not opened its socket yet.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250));
  }
  throw new Error(`${label} did not become ready\n${logs()}`);
}

function signalGroup(child, signal) {
  // Signal the process group, not just the direct child. `npm run dev` runs Next as a
  // grandchild, so a signal addressed to npm alone leaves Next alive holding the stdio
  // pipes this script captured. Node then never drains its event loop and the demo hangs
  // after it has already passed every step, which is how CI sat on this step for hours.
  // Both children are spawned detached so the negated pid addresses the whole group.
  try {
    process.kill(-child.pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      // Already reaped.
    }
  }
}

async function terminate(child) {
  if (!child || child.exitCode !== null) return;
  // Wait for the group to actually die. Signalling without waiting orphans whatever had
  // not finished shutting down, and the next run then fails assertPortFree on a port its
  // own predecessor is still holding.
  const exited = once(child, "exit");
  signalGroup(child, "SIGTERM");
  const escalation = setTimeout(() => signalGroup(child, "SIGKILL"), 5_000);
  try {
    await exited;
  } finally {
    clearTimeout(escalation);
  }
}

async function assertPortFree(port) {
  await new Promise((resolveCheck, rejectCheck) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    socket.once("connect", () => {
      socket.destroy();
      rejectCheck(new Error(`demo port ${port} is already in use; stop the stale service`));
    });
    socket.once("error", () => {
      socket.destroy();
      resolveCheck();
    });
  });
}

async function run(options) {
  const selected = selectSteps(options.from);
  if (options.list) {
    for (const step of STEPS) {
      console.log(`${step.id}: ${step.title}\n${step.presenterNotes}\n`);
    }
    return;
  }

  const scratch = mkdtempSync(join(tmpdir(), "hrz7-demo-"));
  const python = process.env.PYTHON || (
    existsSync(join(ROOT_DIR, ".venv", "bin", "python"))
      ? join(ROOT_DIR, ".venv", "bin", "python")
      : "python"
  );
  let api;
  let ui;
  let browser;
  try {
    await assertPortFree(18087);
    await assertPortFree(13007);
    api = spawn(
      python,
      ["-m", "uvicorn", "review_console.api.app:app", "--host", "127.0.0.1", "--port", "18087"],
      {
        cwd: ROOT_DIR,
        env: {
          ...process.env,
          REVIEW_PROFILE: "local",
          REVIEW_DB_PATH: join(scratch, "reviews.sqlite3"),
          REVIEW_CORS_ORIGINS: UI_URL,
        },
        stdio: ["ignore", "pipe", "pipe"],
        detached: true,
      },
    );
    const apiLogs = captureOutput(api, "api");
    await waitForReady(`${API_URL}/healthz`, api, apiLogs, "API");

    ui = spawn(
      "npm",
      ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", "13007"],
      {
        cwd: UI_DIR,
        env: {
          ...process.env,
          NEXT_TELEMETRY_DISABLED: "1",
          NEXT_PUBLIC_REVIEW_API_URL: API_URL,
        },
        stdio: ["ignore", "pipe", "pipe"],
        detached: true,
      },
    );
    const uiLogs = captureOutput(ui, "ui");
    await waitForReady(UI_URL, ui, uiLogs, "UI");

    const { chromium } = await import("playwright");
    browser = await chromium.launch({ headless: options.headless, slowMo: options.slowMo });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    if (options.screenshots) mkdirSync(options.screenshots, { recursive: true });

    for (const [index, step] of selected.entries()) {
      console.log(`\n[${step.id}] ${step.title}\n${step.presenterNotes}\n`);
      await step.action(page);
      if (options.screenshots) {
        const number = String(index + 1).padStart(2, "0");
        await page.screenshot({
          path: join(options.screenshots, `${number}-${step.id}.png`),
          fullPage: true,
        });
      }
      await pauseAfter(options);
    }
  } finally {
    await browser?.close();
    await terminate(ui);
    await terminate(api);
    rmSync(scratch, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run(parseArgs(process.argv.slice(2)))
    .catch((error) => {
      console.error(error instanceof Error ? error.stack : error);
      process.exitCode = 1;
    })
    .finally(() => {
      // The verdict is settled once cleanup has run, so leave on it rather than waiting for
      // the event loop to drain. A single surviving grandchild is otherwise enough to hold
      // this process open indefinitely, which reports as a hung job rather than a failure.
      process.exit(process.exitCode ?? 0);
    });
}
