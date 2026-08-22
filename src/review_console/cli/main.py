"""Minimal stdlib CLI: submit a review, list a tenant's queue, or dispose of an item (argparse).

The CLI passes an explicit ``--actor`` / ``--tenant`` / ``--groups`` to stand in for the
server-verified principal the API derives from identity, so the four-eyes rule is demoable
offline: disposing as the maker is refused, disposing as a distinct approver is allowed.

The case, clock & workflow engine is exposed under the ``cases`` subcommand
(``review-console cases open|transition|evaluate|list``).
"""

from __future__ import annotations

import argparse
import sys
import uuid

from ..config import Container, build_container
from ..domain.cases.sample_workflows import SAMPLE_DEFINITIONS
from ..domain.cases.workflow_service import CaseWorkflowService
from ..domain.console_service import ConsoleService
from ..domain.kernel import Disposition, Severity


def _console() -> ConsoleService:
    return build_container().console


def _case_service(container: Container) -> CaseWorkflowService:
    return CaseWorkflowService(
        container.case_store,
        container.audit,
        definitions=SAMPLE_DEFINITIONS,
        events=container.events,
        timers=container.timers,
        review_router=container.review_router,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review-console")
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="Submit an item for review.")
    submit.add_argument("action")
    submit.add_argument("subject")
    submit.add_argument("--summary", default="")
    submit.add_argument("--maker", default="demo.analyst@bank.example")
    submit.add_argument("--tenant", default="demo-bank")
    submit.add_argument("--severity", default="high", choices=[s.value for s in Severity])
    submit.add_argument("--approvals", type=int, default=1)
    submit.add_argument("--sod-group", default="")

    decide = sub.add_parser("decide", help="Approve / reject / amend an item as a checker.")
    decide.add_argument("review_id")
    decide.add_argument("disposition", choices=[d.value for d in Disposition])
    decide.add_argument("--checker", default="demo.approver@bank.example")
    decide.add_argument("--tenant", default="demo-bank")
    decide.add_argument("--groups", default="group:analyst,group:approver")
    decide.add_argument("--reason", default="reviewed")

    queue = sub.add_parser("queue", help="List the pending queue for a tenant.")
    queue.add_argument("--tenant", default="demo-bank")

    cases = sub.add_parser("cases", help="Case, clock & workflow engine commands.")
    cases_sub = cases.add_subparsers(dest="cases_command", required=True)

    c_open = cases_sub.add_parser("open", help="Open a case.")
    c_open.add_argument("case_type")
    c_open.add_argument("--tenant", default="demo-bank")
    c_open.add_argument("--actor", default="demo.analyst@bank.example")
    c_open.add_argument("--severity", default="medium", choices=[s.value for s in Severity])

    c_tr = cases_sub.add_parser("transition", help="Advance a case to a new state.")
    c_tr.add_argument("case_id")
    c_tr.add_argument("to_state")
    c_tr.add_argument("--tenant", default="demo-bank")
    c_tr.add_argument("--actor", default="demo.analyst@bank.example")
    c_tr.add_argument("--reason", default="")

    c_ev = cases_sub.add_parser("evaluate", help="Assess a case's clocks and escalation.")
    c_ev.add_argument("case_id")
    c_ev.add_argument("--tenant", default="demo-bank")

    c_ls = cases_sub.add_parser("list", help="List a tenant's cases.")
    c_ls.add_argument("--tenant", default="demo-bank")

    args = parser.parse_args(argv)

    if args.command == "cases":
        return _run_cases(args)

    console = _console()

    if args.command == "submit":
        item = console.submit(
            review_id=uuid.uuid4().hex,
            maker=args.maker,
            tenant=args.tenant,
            action=args.action,
            subject=args.subject,
            summary=args.summary,
            severity=Severity(args.severity),
            required_approvals=args.approvals,
            sod_group=args.sod_group,
        )
        print(f"submitted {item.review_id}: {item.request.action} [{item.state.value}]")
        return 0

    if args.command == "decide":
        groups = tuple(g.strip() for g in args.groups.split(",") if g.strip())
        outcome = console.dispose(
            review_id=args.review_id,
            checker=args.checker,
            checker_tenant=args.tenant,
            checker_groups=groups,
            disposition=Disposition(args.disposition),
            reason=args.reason,
        )
        if outcome.allowed:
            print(f"{args.disposition}: {outcome.item.review_id} -> {outcome.item.state.value}")
            return 0
        print(f"DENIED: {', '.join(f.value for f in outcome.findings)}", file=sys.stderr)
        return 1

    if args.command == "queue":
        for item in console.list_queue(args.tenant):
            req = item.request
            print(f"{item.review_id}  {req.severity.value:8}  {req.action}  by {req.maker}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


def _run_cases(args: argparse.Namespace) -> int:
    """Dispatch the ``cases`` subcommand (the case-workflow engine)."""
    service = _case_service(build_container())

    if args.cases_command == "open":
        case = service.open_case(
            case_id=uuid.uuid4().hex,
            tenant=args.tenant,
            case_type=args.case_type,
            actor=args.actor,
            severity=Severity(args.severity),
        )
        print(f"opened {case.case_id}: {case.case_type} [{case.state}]")
        return 0

    if args.cases_command == "transition":
        from ..domain.cases.state_machine import IllegalTransition

        try:
            case = service.transition_case(
                case_id=args.case_id,
                tenant=args.tenant,
                to_state=args.to_state,
                actor=args.actor,
                reason=args.reason,
            )
        except IllegalTransition as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        print(f"{case.case_id}: -> {case.state}")
        return 0

    if args.cases_command == "evaluate":
        assessment = service.evaluate_case(case_id=args.case_id, tenant=args.tenant)
        findings = [f.value for f in assessment.findings]
        print(f"{assessment.case_id} [{assessment.state}] findings={findings}")
        print(f"  requires_human_review: {assessment.requires_human_review}")
        for d in assessment.deadlines:
            flag = "BREACHED" if d.breached else ("APPROACHING" if d.approaching else "ok")
            print(f"  {d.clock}: {d.remaining_days}d remaining [{flag}]")
        return 0

    if args.cases_command == "list":
        for case in service.list_cases(args.tenant):
            print(f"{case.case_id}  {case.case_type}  {case.state}  {case.severity.value}")
        return 0

    return 2  # pragma: no cover - argparse requires a sub-subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
