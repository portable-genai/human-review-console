"""The vendored catalog skills are not this repo's code, so the formatter must leave them alone.

``.agents/skills/`` is a copy of the canonical artifacts in the maintainer's shared agent
skills. A
repo-local ``ruff format`` run over the whole tree once reflowed the vendored Python and forked it
from its source. The exclusion below is what prevents that; this guard keeps the exclusion (and
only that exclusion) in place, without narrowing the gate over ``src/``, ``tests/`` or ``eval/``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_vendored_skill_tree_is_excluded_from_formatting() -> None:
    excluded = _PYPROJECT["tool"]["ruff"].get("extend-exclude", [])
    assert ".agents" in excluded


def test_the_repo_s_own_code_is_never_excluded_from_the_gate() -> None:
    excluded = set(_PYPROJECT["tool"]["ruff"].get("extend-exclude", [])) | set(
        _PYPROJECT["tool"]["ruff"].get("exclude", [])
    )
    for owned in ("src", "tests", "eval", "scripts"):
        assert owned not in excluded, f"{owned}/ must stay inside lint and format"
