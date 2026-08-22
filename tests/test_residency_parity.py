"""D5 (code and config half): residency is one allowlist, enforced at plan time AND at app load.

Terraform rejects an out-of-country region before an apply; the process refuses to boot with one.
The drift guard below is the point: if someone widens the Terraform validation without widening
``RESIDENCY_ALLOWLIST`` (or the reverse), the two enforcement points would disagree and one of
them would be decorative. These assertions cannot prove LIVE enforcement on a real project, which
needs a named deployment; they prove the posture is coded consistently in both places.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from review_console.config import REGION, RESIDENCY_ALLOWLIST, Settings

_TERRAFORM = Path(__file__).resolve().parents[1] / "infra" / "terraform"


def _terraform_region_allowlist() -> set[str]:
    """The region values ``variables.tf`` validates a plan against."""
    body = (_TERRAFORM / "variables.tf").read_text(encoding="utf-8")
    match = re.search(r"condition\s*=\s*contains\(\[([^\]]*)\],\s*var\.region\)", body)
    assert match is not None, "variables.tf no longer validates var.region against a list"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_terraform_and_application_share_one_residency_allowlist() -> None:
    assert _terraform_region_allowlist() == set(RESIDENCY_ALLOWLIST)


def test_org_policy_locations_cover_exactly_the_allowlisted_regions() -> None:
    locals_body = (_TERRAFORM / "locals.tf").read_text(encoding="utf-8")
    match = re.search(r"allowed_locations\s*=\s*\[([^\]]*)\]", locals_body)
    assert match is not None, "locals.tf no longer declares allowed_locations"
    locations = set(re.findall(r'"in:([^"]+)-locations"', match.group(1)))
    assert locations == set(RESIDENCY_ALLOWLIST)


def test_the_default_region_is_inside_the_allowlist() -> None:
    assert REGION in RESIDENCY_ALLOWLIST
    assert Settings(profile="local").region == REGION


def test_an_out_of_country_region_refuses_to_construct() -> None:
    with pytest.raises(ValueError, match="residency allowlist"):
        Settings(profile="gcp", region="europe-west1")


def test_the_perimeter_is_dry_run_first_and_toggled_by_variable() -> None:
    """A perimeter that defaults to enforced locks reviewers out before the dry run is clean."""
    variables = (_TERRAFORM / "variables.tf").read_text(encoding="utf-8")
    enforce_block = re.search(
        r'variable\s+"vpc_sc_enforce"\s*\{.*?\n\}', variables, flags=re.DOTALL
    )
    assert enforce_block is not None, "vpc_sc_enforce variable is missing"
    assert re.search(r"default\s*=\s*false", enforce_block.group(0))

    perimeter = (_TERRAFORM / "vpc_sc.tf").read_text(encoding="utf-8")
    assert "google_access_context_manager_service_perimeter" in perimeter
    assert "use_explicit_dry_run_spec = !var.vpc_sc_enforce" in perimeter


def test_a_posture_alert_exists_for_perimeter_violations_and_key_events() -> None:
    monitoring = (_TERRAFORM / "monitoring.tf").read_text(encoding="utf-8")
    for signal in ("vpc_sc_violation", "sa_key_creation", "cmek_change", "residency_violation"):
        assert signal in monitoring, f"no posture alert for {signal}"
    assert "google_monitoring_alert_policy" in monitoring


def test_cmek_is_bound_per_service_rather_than_project_wide() -> None:
    kms = (_TERRAFORM / "kms.tf").read_text(encoding="utf-8")
    members = re.findall(r'google_kms_crypto_key_iam_member"\s+"([a-z_]+)"', kms)
    assert {"firestore", "run"} <= set(members)
    assert "google_kms_crypto_key_iam_binding" not in kms
