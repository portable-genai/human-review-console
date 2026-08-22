"""Case, clock & workflow domain core.

Pure-stdlib and deterministic: a state machine with full transition history, SLA / regulatory
clock maths with business-day deadlines, and the escalation assessment. Nothing here imports a web
framework or a cloud SDK. Shares the console's ``Severity`` / ``Citation`` / ``utcnow`` kernel
(``review_console.domain.kernel``); the case-specific taxonomies live in ``.kernel``.

The engine owns NO vertical policy: a consumer supplies its own states, transitions, clocks and
escalation rules as a ``WorkflowDefinition``. A consequential escalation routes softly to the
review console (in-process, via ``ReviewRouterPort``); the engine never auto-executes.
"""
