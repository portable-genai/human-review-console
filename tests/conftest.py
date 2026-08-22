"""Test-session environment: select the offline profile DELIBERATELY.

The seeded-persona identity adapter refuses to serve when ``REVIEW_PROFILE`` is absent (see
``adapters/local/identity.py``): an unset profile must not silently hand out approver personas.
The gate is an offline local run, so the harness makes that choice explicit here rather than
relying on a fallback, exactly as the Makefile and CI workflow do.
"""

from __future__ import annotations

import os

os.environ.setdefault("REVIEW_PROFILE", "local")
