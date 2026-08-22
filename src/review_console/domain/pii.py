"""The PII pattern set this deployment redacts with, sourced from the shared ``pii-kit``.

The console stores review subjects, summaries and reviewer reasons that originate from verticals
whose payloads can carry customer identifiers, so it redacts them before they reach the WORM
sign-off record (defense in depth: the console holds no customer PII by design, but never trusts
that an upstream summary is clean). Row selection and ORDER are per-deployment: national-ID rows
run first, the universal email / phone rows last.
"""

from __future__ import annotations

from pii_kit import UNIVERSAL_PATTERNS, Pattern, national_patterns_for

#: The jurisdictions this deployment serves (override per client). Obviously synthetic data only.
JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")

PII_PATTERNS: tuple[Pattern, ...] = (
    *national_patterns_for(JURISDICTIONS),
    *UNIVERSAL_PATTERNS,
)
