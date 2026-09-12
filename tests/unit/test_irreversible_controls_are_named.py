"""An irreversible control never arrives by default.

The sign-off bucket's lock is the one control in ``infra/terraform/`` that cannot be undone: a
locked Cloud Logging bucket refuses to be deleted or to have its window shortened for the whole
retention period, project owner or not. Here it was the literals ``retention_days = 2555`` and
``locked = true`` with no variable behind either, so the first apply of this stack anywhere took
a seven-year decision whether or not the deployment had made one.

So the lock is ``worm_locked`` with no default and a plan refuses until the deployment states
it, the ~7-year retention floor binds only when the lock is on (an unlocked reference stack may
keep a short window and stay destroyable), and the resource reads both variables.

Observed failing first: against the stack as it shipped, every test here failed, because no
``worm_locked`` and no ``retention_days`` variable existed and the resource carried the literals.
Adding ``default = true`` to the variable turns the no-default test red again, which is the
regression it exists to stop.
"""

from __future__ import annotations

import re
from pathlib import Path

TF = Path(__file__).resolve().parents[2] / "infra" / "terraform"


def _variable_block(name: str) -> str:
    text = (TF / "variables.tf").read_text(encoding="utf-8")
    start = text.find(f'variable "{name}" {{')
    assert start != -1, f"variables.tf declares no {name!r}"
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unterminated variable block {name!r}")


def test_the_sign_off_bucket_lock_is_a_variable_not_a_literal() -> None:
    worm = (TF / "logging_worm.tf").read_text(encoding="utf-8")
    assert re.search(r"^\s*locked\s*=\s*var\.worm_locked\s*$", worm, re.MULTILINE)
    assert not re.search(r"^\s*locked\s*=\s*(true|false)\s*$", worm, re.MULTILINE)
    assert re.search(r"^\s*retention_days\s*=\s*var\.retention_days\b", worm, re.MULTILINE)
    assert not re.search(r"^\s*retention_days\s*=\s*\d+", worm, re.MULTILINE)


def test_the_lock_is_named_worm_locked_and_nothing_else() -> None:
    variables = (TF / "variables.tf").read_text(encoding="utf-8")
    assert 'variable "worm_locked"' in variables
    assert "lock_worm_bucket" not in variables, (
        "the fleet has ONE name for this control, worm_locked, so a deployment tfvars written "
        "for one stack states the lock in every stack"
    )


def test_the_lock_has_no_default_so_every_plan_names_it() -> None:
    block = _variable_block("worm_locked")
    assert not re.search(r"^\s*default\s*=", block, re.MULTILINE), (
        "worm_locked must have no default: an irreversible control must never be taken because "
        "a deployment said nothing, and a fork must never lose it the same way"
    )


def test_the_retention_floor_binds_only_when_locked() -> None:
    block = _variable_block("retention_days")
    assert re.search(r"^\s*default\s*=\s*2557\b", block, re.MULTILINE)
    condition = re.search(r"^\s*condition\s*=\s*(.+)$", block, re.MULTILINE)
    assert condition is not None, "retention_days carries no validation"
    assert re.fullmatch(
        r"var\.worm_locked\s*\?\s*var\.retention_days\s*>=\s*2557\s*:\s*var\.retention_days\s*>=\s*1",
        condition.group(1).strip(),
    ), condition.group(1)


def test_the_example_shows_the_locked_production_form() -> None:
    example = (TF / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert re.search(r"^worm_locked\s*=\s*true\s*$", example, re.MULTILINE)
    assert re.search(r"^retention_days\s*=\s*2557\s*$", example, re.MULTILINE)
