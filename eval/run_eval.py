#!/usr/bin/env python3
"""Evaluation gate for the human-review-console Human-Review & Maker-Checker Console.

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change. It drives the real
  ``ConsoleService`` (maker-checker) and the real ``CaseWorkflowService`` against two golden sets
  with SDK-free local adapters, and scores both sides in ONE report: - ``four_eyes_integrity``: the
  deterministic engine allows every legitimate disposition and DENIES every self-approval /
  cross-tenant / missing-role / SoD / duplicate one. This is the safety metric, so its threshold is
  0.99. - ``pii_safety``: no raw identifier from a review summary or reviewer reason survives into a
  sign-off audit record. - ``clock_accuracy``: the case business-day deadline maths matches the
  hand-computed golden (remaining days and the breach flag). Safety metric, so its threshold is
  0.99. - ``escalation_accuracy``: the case findings and the escalation decision match expectation.
  - ``case_pii_safety``: no raw identifier from a case attribute survives into an audit record. *
  **gate** - the promotion verdict from the shared model-quality-gate authority (requires the
  platform / gcp profile), via ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.adapters.local.case_store import LocalCaseStore
from review_console.adapters.local.review_store import LocalReviewStore
from review_console.config import Settings
from review_console.domain.cases.sample_workflows import SAMPLE_DEFINITIONS
from review_console.domain.cases.workflow_service import CaseWorkflowService
from review_console.domain.console_service import ConsoleService, ReviewNotFound
from review_console.domain.kernel import Disposition, Severity
from review_console.domain.pii import PII_PATTERNS

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_reviews.jsonl"
#: The case golden set, scored beside the review set in the same smoke report.
CASE_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

THRESHOLDS: dict[str, float] = {
    "four_eyes_integrity": 0.99,
    "pii_safety": 0.99,
    "clock_accuracy": 0.99,
    "escalation_accuracy": 0.90,
    "case_pii_safety": 0.99,
}
#: The registered model-quality-gate metric bundle for this platform (model-quality-gate owns the metrics + thresholds).
_BUNDLE = "human-review-console"


def _load(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _score_cases(dataset: Path) -> tuple[EvalMetricResult, ...]:
    """Score the case-engine metrics against the case golden set.

    Drives the real ``CaseWorkflowService`` with SDK-free local adapters: opens each complaint
    case, applies its transitions at fixed times, evaluates at ``as_of`` and checks the
    hand-computed acknowledgement clock, the findings + escalation decision, and that no planted
    identifier survives into an audit record.
    """
    cases = _load(dataset)
    store = LocalCaseStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    service = CaseWorkflowService(store, audit, definitions=SAMPLE_DEFINITIONS)

    clock_scores: list[float] = []
    escalation_scores: list[float] = []

    for i, case in enumerate(cases):
        case_id = f"c{i}"
        attributes = {str(k): str(v) for k, v in dict(case.get("attributes", {})).items()}  # type: ignore[union-attr]
        service.open_case(
            case_id=case_id,
            tenant="demo-bank",
            case_type="complaint",
            actor="eval-bot",
            attributes=attributes,
            as_of=_dt(str(case["opened_at"])),
        )
        for to_state, at in case.get("transitions", []):  # type: ignore[union-attr]
            service.transition_case(
                case_id=case_id,
                tenant="demo-bank",
                to_state=str(to_state),
                actor="eval-bot",
                reason="scenario",
                as_of=_dt(str(at)),
            )
        assessment = service.evaluate_case(
            case_id=case_id, tenant="demo-bank", as_of=_dt(str(case["as_of"]))
        )

        # clock_accuracy: the acknowledgement clock matches the hand-computed golden.
        expected_ack = case.get("expected_ack")
        if expected_ack is not None:
            ack = next((d for d in assessment.deadlines if d.clock == "acknowledgement"), None)
            ok = (
                ack is not None
                and ack.remaining_days == expected_ack["remaining"]  # type: ignore[index]
                and ack.breached == expected_ack["breached"]  # type: ignore[index]
            )
            clock_scores.append(1.0 if ok else 0.0)

        # escalation_accuracy: findings present + the escalation decision.
        found = {f.value for f in assessment.findings}
        expected_findings = {str(f) for f in case.get("expected_findings", [])}  # type: ignore[union-attr]
        esc_ok = expected_findings <= found and assessment.requires_human_review is bool(
            case["expected_escalation"]
        )
        escalation_scores.append(1.0 if esc_ok else 0.0)

    # case_pii_safety: no planted identifier may survive into any audit record.
    records = audit.log.read_all()
    texts = [str(r.get("redacted_summary", "")) for r in records]
    planted = [str(c["planted"]) for c in cases if c.get("planted")]
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in texts)
    literal_leaked = any(token in text for token in planted for text in texts)
    case_pii_safety = 0.0 if (pack_leaked or literal_leaked) else 1.0

    return (
        EvalMetricResult.scored(
            "clock_accuracy", _mean(clock_scores), THRESHOLDS["clock_accuracy"]
        ),
        EvalMetricResult.scored(
            "escalation_accuracy", _mean(escalation_scores), THRESHOLDS["escalation_accuracy"]
        ),
        EvalMetricResult.scored("case_pii_safety", case_pii_safety, THRESHOLDS["case_pii_safety"]),
    )


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    store = LocalReviewStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    console = ConsoleService(store, audit)

    integrity_scores: list[float] = []
    for case in cases:
        console.submit(
            review_id=str(case["id"]),
            maker=str(case["maker"]),
            tenant=str(case["maker_tenant"]),
            action="review",
            subject=str(case.get("summary", "")),
            summary=str(case.get("summary", "")),
            severity=Severity(str(case["severity"])),
            sod_group=str(case.get("sod_group", "")),
        )
        try:
            outcome = console.dispose(
                review_id=str(case["id"]),
                checker=str(case["checker"]),
                checker_tenant=str(case["checker_tenant"]),
                checker_groups=tuple(str(g) for g in case["checker_groups"]),  # type: ignore[union-attr]
                disposition=Disposition(str(case["disposition"])),
                reason=str(case.get("reason", "")),
            )
            allowed = outcome.allowed
        except ReviewNotFound:
            # A cross-tenant checker cannot even see the item: not-found IS a denial.
            allowed = False
        integrity_scores.append(1.0 if allowed is bool(case["expected_allowed"]) else 0.0)

    # pii_safety: no raw identifier may survive into any sign-off record. The pack scan uses the
    # same rows the redactor masks with; the planted-literal check is an independent oracle that
    # fires even if a row is broken (the two-part scorer lesson from the C4 rollout).
    records = audit.log.read_all()
    texts = [f"{r.get('redacted_reason', '')} {r.get('redacted_summary', '')}" for r in records]
    planted = [str(case["planted"]) for case in cases if case.get("planted")]
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in texts)
    literal_leaked = any(token in text for token in planted for text in texts)
    pii_safety = 0.0 if (pack_leaked or literal_leaked) else 1.0

    review_results = (
        EvalMetricResult.scored(
            "four_eyes_integrity", _mean(integrity_scores), THRESHOLDS["four_eyes_integrity"]
        ),
        EvalMetricResult.scored("pii_safety", pii_safety, THRESHOLDS["pii_safety"]),
    )

    # Include the case-engine metrics so ONE gate reports both sides in one table.
    case_cases = _load(CASE_DATASET)
    case_results = _score_cases(CASE_DATASET)

    return EvalReport(
        dataset=f"{dataset} + {CASE_DATASET}",
        results=review_results + case_results,
        n_examples=len(cases) + len(case_cases),
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"REVIEW_PROFILE=platform or gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("REVIEW_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for human-review-console (human-review console).",
        )
    )
