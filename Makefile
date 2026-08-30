.PHONY: help install lint format typecheck test eval check run-api smoke demo demo-json \
	demo-selftest portability-demo ui-install ui-check ui-headers-test terraform-check \
	docker-build clean lock prove-exposure

PY ?= python3
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PY))
PORT ?= 8087
API_HOST ?= 127.0.0.1
export REVIEW_PROFILE ?= local

help: ## List targets.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Editable install with the SDK-free dev toolchain.
	pip install -e ".[dev]"

lint: ## ruff check + format check.
	ruff check src tests eval
	ruff format --check src tests eval

format: ## Auto-format and fix.
	ruff format src tests eval
	ruff check --fix src tests eval

typecheck: ## Static type check (mypy strict).
	mypy src

test: ## Offline pytest suite (local profile).
	pytest -m 'not integration'

eval: ## Offline evaluation gate (smoke; exit non-zero on fail).
	$(PY) eval/run_eval.py

# The full offline hard gate (what CI runs).
portability: ## Execute the bounded offline/profile portability proof.
	PYTHONPATH=src $(PY) scripts/portability_demo.py

prove-exposure: ## Drive the whole exposure matrix over a REAL socket from a REAL LAN peer.
	# The derivation this backs is gated; until now the peer proof was not, so a script that
	# could only be run by hand stood behind a published claim. It refuses rather than skips
	# when this host has no non-loopback address, because a proof that quietly declines to run
	# reports the same green as one that ran.
	bash scripts/prove-exposure-matrix.sh

check: lint typecheck test eval portability prove-exposure ## Lint + typecheck + test + eval + portability + LAN-peer exposure proof.

run-api: ## Serve the API locally (loopback, local profile).
	uvicorn review_console.api.app:app --host $(API_HOST) --port $(PORT) --reload

smoke: ## Submit a review via the CLI then list the queue.
	review-console submit disburse "Acme Holdings (FICTIONAL)" --severity high
	review-console queue --tenant demo-bank

demo: ## Run the headed, presenter-paced live browser walkthrough.
	node ui/scripts/console-demo-playwright.mjs

demo-json: ## Run the offline domain walkthrough (writes the audit view JSON).
	$(PY) scripts/console_demo.py

demo-selftest: ## Run the live presenter demo unattended in Chromium.
	node --test ui/scripts/console-demo-playwright.test.mjs
	node ui/scripts/console-demo-playwright.mjs --no-pause --headless

ui-install: ## Install the console's locked node dependencies.
	npm ci --prefix ui

# The console gate. assert-hydratable runs LAST and against the artefact the build just made:
# it starts that server, fetches the served document and asserts every script tag carries the
# response nonce. Nothing cheaper can see the failure it exists for, because the CSP header is
# byte-identical whether the page hydrates or ships as dead markup.
ui-check: ## Type-check, unit-test, build and hydration-prove the console.
	npm --prefix ui run lint
	npm --prefix ui test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix ui run build
	npm --prefix ui run assert-hydratable

ui-headers-test: ## Unit-test the UI security-header policy only (no build, no server).
	node --test ui/scripts/security-headers.test.mjs

terraform-check: ## Offline terraform fmt + validate (no backend, no cloud credentials).
	terraform -chdir=infra/terraform init -backend=false -input=false
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform validate

portability-demo: ## Run the bounded offline profile and audit portability proof.
	$(PY) scripts/portability_demo.py

docker-build: ## Build the serving image.
	docker build -t human-review-console:dev .

lock: ## Recompile the dependency lockfiles with uv (needs network).
	python3 scripts/lock.py

clean: ## Remove caches and build artifacts.
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info
