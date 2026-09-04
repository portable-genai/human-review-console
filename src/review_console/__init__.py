"""human-review-console Human-Review & Maker-Checker Console.

The shared destination for every ``requires_human_review`` escalation the catalog raises: a
tenant-partitioned review queue, four-eyes / segregation-of-duties routing, approve / reject /
amend with a reason, and a WORM sign-off record proving who approved what and when. This is the
system enforcer for principle P-06 ("escalates softly to a human, never auto-executes"), which
until now terminated in a per-repo boolean with no queue, no reviewer UI and no sign-off evidence.

A hexagonal ports-and-adapters build on the catalog commons: a pure-stdlib deterministic
maker-checker core, typed ports, swappable adapter profiles (local / gcp / platform / onprem), a DI
container driven by one env var, and a green SDK-free offline gate. Identity, S2S, fail-closed
network defaults and the WORM audit log come from ``hex-service-kit``; the eval scaffold from
``agent-eval-kit``; the PII pattern pack from ``pii-kit``.

The console owns NO vertical policy. Each consumer supplies its own routing policy (how many
approvals an action needs, which segregation group a maker sits in) as configuration, exactly as
agent-guardrail-gateway the Guardrail Gateway owns no vertical prompt.
"""

from __future__ import annotations

__version__ = "0.0.1"
