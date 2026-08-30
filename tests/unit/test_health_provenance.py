"""The banner's server half: this console names its runtime, and says it has no model.

Every served UI in the fleet states, at the top of every page, where it is running and
which model answers (org decision, 2026-08-30). The console must never infer either.

This one is the interesting case in the sweep. It declares no ``llm`` port at all: routing,
SLA clocks and quorum are deterministic, and the decision itself is a human's. So it answers
``no-model``, which is materially different from ``deterministic-offline-stub``. The stub
string means a model-shaped port is bound to a deterministic implementation and could be
rebound to a real model tomorrow; ``no-model`` means there is nothing to rebind. A reviewer
approving an escalation is entitled to know which of the two they are looking at, and
collapsing them into one string would tell them the wrong one.
"""

from __future__ import annotations

import dataclasses

import pytest

from review_console.config import Settings


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("local", "local"), ("gcp", "gcp"), ("platform", "gcp"), ("onprem", "local")],
)
def test_the_runtime_says_where_the_process_runs(profile: str, expected: str) -> None:
    assert dataclasses.replace(Settings(), profile=profile).runtime == expected


@pytest.mark.parametrize("profile", ["local", "gcp", "platform", "onprem"])
def test_a_console_with_no_model_says_so_under_every_profile(profile: str) -> None:
    """The answer does not vary, because the absence is structural rather than configured.

    There is no binding table here to read a model out of. That is why this returns a
    constant while every other repo in the sweep derives its value: if this console ever
    grows an ``llm`` port, this test fails and the property has to be rewritten to read
    that binding, which is the right amount of friction for adding a model to a
    human-review surface.
    """
    assert dataclasses.replace(Settings(), profile=profile).generator_model == "no-model"


def test_no_model_is_not_the_same_claim_as_a_deterministic_stub() -> None:
    """Stated as an assertion because the two are easy to conflate when sweeping."""
    assert Settings().generator_model != "deterministic-offline-stub"
