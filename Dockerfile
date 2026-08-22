# Hrz7 Human-Review & Maker-Checker Console serving image.
# Digest-pinned slim base (dependabot bumps the digest + the lockfile); multi-stage so the build
# toolchain never reaches the runtime layer; non-root; healthchecked; installs from the committed
# gcp lockfile so the image matches pip-audit and CI byte-for-byte.

# --------------------------------------------------------------------------- #
# Stage 1: builder. git is needed only while pip resolves the git+https commons
# pins. It lives and dies here: the runtime stage below copies the virtualenv,
# never this filesystem, so no compiler, no git and no pip cache can ship.
# --------------------------------------------------------------------------- #
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY requirements-gcp.lock ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements-gcp.lock \
 && /opt/venv/bin/pip install --no-deps .

# --------------------------------------------------------------------------- #
# Stage 2: runtime. The same digest-pinned slim base with only the virtualenv,
# the shipped policy document and the application configuration copied in.
# --------------------------------------------------------------------------- #
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8087 \
    REVIEW_PROFILE=gcp

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# The bank-owned policy document (B4). An institution mounts its own over this path or points
# REVIEW_POLICY_PATH elsewhere; the shipped copy equals the reference defaults.
COPY config ./config

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
USER app

EXPOSE 8087

# The image proves its own liveness rather than relying on the orchestrator's probe: the same
# /healthz the Cloud Run startup probe uses, over loopback, with no extra package installed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8087')+'/healthz',timeout=4).read()"]

# The image defaults to the SECURE profile (D4): identity is the IAP adapter, which fails closed
# without a configured audience and entitlement map. Cloud Run sets the same value explicitly. A
# dev or demo run opts DOWN to seeded personas with REVIEW_PROFILE=local, never the reverse.
CMD ["sh", "-c", "exec uvicorn review_console.api.app:app --host 0.0.0.0 --port ${PORT:-8087}"]
