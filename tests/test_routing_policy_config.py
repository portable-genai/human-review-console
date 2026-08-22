"""B4: the bank-owned routing numbers are configuration, not engine constants.

Two things must hold at once: the SHIPPED policy document reproduces the reference behavior
exactly (so adopting the file changes nothing), and an OVERRIDE actually changes what the running
console does (so the file is load-bearing rather than decorative).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_console.config import DEFAULT_POLICY_PATH, Settings, build_container
from review_console.domain.kernel import Severity
from review_console.domain.maker_checker_service import DEFAULT_ROUTING, RoutingPolicy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHIPPED_POLICY = _REPO_ROOT / DEFAULT_POLICY_PATH


def _settings(policy_path: Path | str) -> Settings:
    return Settings(profile="local", audit_path=":memory:", policy_path=str(policy_path))


def test_shipped_policy_file_exists_and_reproduces_the_reference_defaults() -> None:
    document = json.loads(_SHIPPED_POLICY.read_text(encoding="utf-8"))
    policy = RoutingPolicy.from_mapping(document["policy"]["routing"])
    assert policy == DEFAULT_ROUTING


def test_container_binds_the_configured_policy() -> None:
    container = build_container(_settings(_SHIPPED_POLICY))
    assert container.routing_policy == DEFAULT_ROUTING


def test_override_raises_the_approval_floor_for_a_running_console(tmp_path: Path) -> None:
    """The load-bearing half: an institution that tightens MEDIUM gets dual control for MEDIUM."""
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps({"policy": {"routing": {"min_approvals_by_severity": {"medium": 2}}}}),
        encoding="utf-8",
    )
    container = build_container(_settings(policy_file))

    item = container.console.submit(
        review_id="rev-override",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Acme Holdings (FICTIONAL)",
        summary="disburse facility",
        severity=Severity.MEDIUM,
    )
    assert item.request.required_approvals == 2

    # The default-configured console leaves the very same request at a single approval.
    default_item = build_container(_settings(_SHIPPED_POLICY)).console.submit(
        review_id="rev-default",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Acme Holdings (FICTIONAL)",
        summary="disburse facility",
        severity=Severity.MEDIUM,
    )
    assert default_item.request.required_approvals == 1


def test_override_can_retune_sod_and_the_approver_entitlement(tmp_path: Path) -> None:
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps(
            {"policy": {"routing": {"enforce_sod": False, "approver_group": "group:signatory"}}}
        ),
        encoding="utf-8",
    )
    policy = build_container(_settings(policy_file)).routing_policy
    assert policy.enforce_sod is False
    assert policy.approver_group == "group:signatory"
    # Unnamed keys keep the reference defaults rather than resetting to nothing.
    assert policy.min_approvals_by_severity == DEFAULT_ROUTING.min_approvals_by_severity


def test_a_missing_policy_file_falls_back_to_the_reference_defaults(tmp_path: Path) -> None:
    assert build_container(_settings(tmp_path / "absent.json")).routing_policy == DEFAULT_ROUTING


@pytest.mark.parametrize(
    "section",
    [
        {"min_approvals_by_severity": {"eventually": 2}},  # typo in a severity name
        {"min_approvals_by_severity": {"high": 0}},  # a floor below one approval
        {"min_approvals_by_severity": [2]},  # wrong shape entirely
    ],
)
def test_an_invalid_policy_fails_loudly_instead_of_downgrading_control(
    tmp_path: Path, section: object
) -> None:
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({"policy": {"routing": section}}), encoding="utf-8")
    with pytest.raises(ValueError):
        _ = build_container(_settings(policy_file)).routing_policy
