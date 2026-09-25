"use client";

import { useEffect, useState } from "react";

import { watchAnswers } from "../lib/answer-provenance.mjs";
import { api, BASE_URL } from "../lib/api";

/**
 * Small pills at the top right of every page: the model that ANSWERED, and `Search` when the
 * answer used an online search tool (owner decision, 2026-09-23; they replace the full-width
 * provenance banner).
 *
 * The pill names what answered, not what configuration would call. Until an answer arrives it
 * shows the service's configured `generator_model` from `/healthz`, dimmed, with where the
 * runtime sits in its title. From then on it shows the `X-Answered-By` header of the console's
 * last answering response, solid, and `Search` appears only while that response carried
 * `X-Search-Used: true`. Both headers are emitted by the service (`install_answer_provenance` in
 * `api/app.py`), which also exposes them to this cross-origin page. This service binds no model
 * port, so today the pill shows `no-model` and stays there: nothing a human decides here was
 * answered by a model, and the pill says so rather than staying blank.
 *
 * **Every value comes from the service**, and nothing here infers one. A UI that read its own
 * runtime from `window.location` would be right until the deployment served through a proxy,
 * and wrong silently after that. The health call goes through the same client, and so the same
 * resolved base and `connect-src`, as every other call this console makes.
 */

interface Configured {
  model: string;
  where: string;
}

interface Answer {
  model: string;
  search: boolean;
}

// This console is light-only (`color-scheme: light` in globals.css), so the pills carry no
// dark-scheme variant: one would invert them against a page that stays light.
const PILL =
  "max-w-[260px] truncate rounded-full border px-[9px] py-px text-[11px] leading-[1.6]";

/**
 * Renders once the service has answered `/healthz`, and nothing before that.
 *
 * The null-until-known state is deliberate: a pill defaulting to a model or a runtime while the
 * fetch is in flight would state a falsehood on some page load, and a failed health call renders
 * nothing for the same reason. The page's own error surface owns the failure.
 */
export function ModelPills() {
  const [configured, setConfigured] = useState<Configured | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    let live = true;
    const stop = watchAnswers(window, BASE_URL, (next) => {
      if (live) setAnswer(next);
    });
    api
      .health()
      .then((status) => {
        if (!live || !status?.runtime) return;
        setConfigured({
          model: String(status.generator_model ?? ""),
          where: status.runtime === "gcp" ? "running on GCP" : "running locally",
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
      stop();
    };
  }, []);

  if (!configured) return null;
  return (
    <div
      className="fixed right-[10px] top-[6px] z-20 flex max-w-[calc(100vw-20px)] gap-1.5"
      data-testid="model-pills"
    >
      {answer ? (
        <span
          className={`${PILL} border-gray-900 bg-gray-900 text-white`}
          data-state="answered"
          title="answered the last request"
        >
          {answer.model}
        </span>
      ) : (
        <span
          className={`${PILL} border-dashed border-gray-300 bg-gray-50 text-gray-500`}
          data-state="configured"
          title={configured.where}
        >
          {configured.model}
        </span>
      )}
      {answer?.search ? (
        <span
          className={`${PILL} border-emerald-600 bg-emerald-600 text-white`}
          title="the last answer used an online search tool"
        >
          Search
        </span>
      ) : null}
    </div>
  );
}
