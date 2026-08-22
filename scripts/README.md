# Scripts

Demo and operational helpers, outside the CI gate.

- `console_demo.py` - the offline maker-checker walkthrough: submit an item, show four-eyes
  refusing the maker's self-approval, collect two distinct approvals under dual control, and print
  the hash-chained WORM sign-off trail. Deterministic, synthetic data. Writes `console_demo.json`.

Run with `make demo-json` or `python scripts/console_demo.py`.

- `portability_demo.py` - bounded executable proof for profile map completeness, deterministic
  decisions, local audit integrity, explicit managed bindings, and fail-fast exit behavior.
- `rename_fork.py` - dry-run-first mechanical fork rename for package, command, environment
  prefix, distribution, and cloud resource ids.
- `prove-exposure-matrix.sh` - the loopback exposure guard's standing proof, over a REAL socket.
  Drives `REVIEW_PROFILE` (unset, empty, mis-capitalised, `local`, `onprem`, `gcp`, `platform`) x
  `REVIEW_S2S_TOKEN` (unset, empty, set) x `X-Dev-Persona` (absent, approver) against uvicorn
  bound to `0.0.0.0`, probing from this machine's own LAN address, and requires every cell to
  refuse or to refuse to boot. `tests/test_serving_path_exposure.py` covers the same ground with a
  TestClient in the offline gate; only a bound server proves what a stranger actually gets. Run it
  with `bash scripts/prove-exposure-matrix.sh`.

The headed live browser walkthrough and its unit tests live under `ui/scripts/` because Playwright
is a pinned UI demo dependency. Run it with `make demo`; run its unattended gate with
`make demo-selftest`.
