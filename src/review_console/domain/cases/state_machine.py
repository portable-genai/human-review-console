"""The deterministic state machine: legal transitions with a full append-only history.

Pure and replayable: a transition is either legal for the consumer's ``WorkflowDefinition`` or it
is refused (``IllegalTransition``), and a legal transition returns a new ``Case`` with one more
history entry. No I/O, no clock read; ``as_of`` is passed in.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .models import Case, Transition, WorkflowDefinition


class IllegalTransition(ValueError):
    """Raised when a (from_state, to_state) edge is not in the workflow definition (HTTP 409)."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(f"illegal transition {from_state!r} -> {to_state!r}")
        self.from_state = from_state
        self.to_state = to_state


def legal_next_states(case: Case, definition: WorkflowDefinition) -> tuple[str, ...]:
    """The states the case may legally move to next, in definition order."""
    return tuple(s for s in definition.states if definition.is_legal(case.state, s))


def transition(
    case: Case,
    to_state: str,
    *,
    actor: str,
    reason: str,
    as_of: datetime,
    definition: WorkflowDefinition,
) -> Case:
    """Advance the case to ``to_state`` if the edge is legal, appending to its history."""
    if not definition.is_legal(case.state, to_state):
        raise IllegalTransition(case.state, to_state)

    entry = Transition(
        seq=case.next_seq,
        from_state=case.state,
        to_state=to_state,
        actor=actor,
        reason=reason,
        at=as_of,
    )
    return replace(case, state=to_state, history=(*case.history, entry))
