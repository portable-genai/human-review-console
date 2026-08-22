"""G2: the compliance mapping is real - every evidence pointer resolves, and the crosswalk is owned.

A mapping table whose file references have rotted is worse than no table: it reads as evidence and
is not. These tests walk every backticked path in COMPLIANCE.md and fail on the first one that does
not exist, and assert that the regulator crosswalk names an accountable owner rather than implying
the repository maintainers carry it.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMPLIANCE = (_ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
_CROSSWALK_HEADING = "## Appendix: regulator crosswalk (adopter-owned)"

# A backticked token that looks like a repository path (has a slash or a known extension) and is
# not a code identifier, an env var or a URL.
_PATH_TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|json|tf|md|mjs|ts|tsx|yaml|yml))`")


def _referenced_paths() -> set[str]:
    paths = set()
    for token in _PATH_TOKEN.findall(_COMPLIANCE):
        if token.startswith("http") or "(" in token:
            continue
        paths.add(token)
    return paths


def test_every_evidence_pointer_names_a_file_that_exists() -> None:
    referenced = _referenced_paths()
    assert referenced, "COMPLIANCE.md stopped naming any evidence file"
    missing = []
    for token in sorted(referenced):
        candidates = [
            _ROOT / token,
            _ROOT / "src" / "review_console" / token,
            _ROOT / "infra" / "terraform" / token,
        ]
        if not any(candidate.exists() for candidate in candidates):
            missing.append(token)
    assert not missing, f"COMPLIANCE.md points at files that do not exist: {missing}"


def test_the_regulator_crosswalk_appendix_exists() -> None:
    assert _CROSSWALK_HEADING in _COMPLIANCE


def test_the_crosswalk_states_an_accountable_owner() -> None:
    appendix = _COMPLIANCE.split(_CROSSWALK_HEADING, 1)[1]
    assert "Accountable owner:" in appendix
    assert "Head of Compliance" in appendix
    # It must disclaim, in the appendix itself, that upstream does not own it.
    assert "not legal advice" in appendix
    assert "docs/ADOPTING.md" in appendix


def test_the_crosswalk_maps_controls_to_a_named_supervisor_instrument() -> None:
    appendix = _COMPLIANCE.split(_CROSSWALK_HEADING, 1)[1]
    rows = [line for line in appendix.splitlines() if line.startswith("| P-")]
    assert len(rows) >= 5, "the crosswalk has too few mapped controls to be useful"
    for row in rows:
        assert any(instrument in row for instrument in ("MAS", "PDPA")), (
            f"crosswalk row names no supervisory instrument: {row}"
        )
        assert row.count("|") >= 5, f"crosswalk row is missing a column: {row}"


def test_adopting_guide_routes_the_crosswalk_to_its_owner() -> None:
    adopting = (_ROOT / "docs" / "ADOPTING.md").read_text(encoding="utf-8")
    assert "crosswalk" in adopting.lower()
    assert "COMPLIANCE.md" in adopting
