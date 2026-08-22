"""Case API surface: verified-principal identity, cross-tenant 404, illegal 409, S2S, headers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from review_console.api.app import app

_TOKEN_ENV = "REVIEW_S2S_TOKEN"


def _client() -> TestClient:
    # An explicit LOOPBACK peer: the app object carries the exposure guard, and Starlette's
    # default test peer is the non-loopback literal ``testclient`` (see ``_client`` in
    # ``tests/test_api.py`` and the guard's own proofs in ``test_serving_path_exposure.py``).
    return TestClient(app, client=("127.0.0.1", 51234))


def _open(client: TestClient, persona: str = "analyst") -> str:
    resp = client.post(
        "/v1/cases",
        json={"case_type": "complaint", "severity": "medium"},
        headers={"X-Dev-Persona": persona},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["case_id"]


def test_open_stamps_tenant_from_principal() -> None:
    client = _client()
    resp = client.post(
        "/v1/cases",
        json={"case_type": "complaint"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant"] == "demo-bank"
    assert body["state"] == "received"
    assert body["legal_next_states"] == ["under_review"]


def test_unknown_case_type_is_422() -> None:
    resp = _client().post(
        "/v1/cases", json={"case_type": "nope"}, headers={"X-Dev-Persona": "analyst"}
    )
    assert resp.status_code == 422


def test_legal_transition_advances_state() -> None:
    client = _client()
    case_id = _open(client)
    resp = client.post(
        f"/v1/cases/{case_id}/transition",
        json={"to_state": "under_review", "reason": "triage"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "under_review"


def test_illegal_transition_is_409() -> None:
    client = _client()
    case_id = _open(client)
    resp = client.post(
        f"/v1/cases/{case_id}/transition",
        json={"to_state": "resolved"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert resp.status_code == 409


def test_cross_tenant_get_is_404() -> None:
    client = _client()
    case_id = _open(client, "analyst")  # demo-bank
    resp = client.get(f"/v1/cases/{case_id}", headers={"X-Dev-Persona": "other-tenant"})
    assert resp.status_code == 404


def test_evaluate_returns_deadlines() -> None:
    client = _client()
    case_id = _open(client)
    resp = client.post(f"/v1/cases/{case_id}/evaluate", headers={"X-Dev-Persona": "analyst"})
    assert resp.status_code == 200
    clocks = {d["clock"] for d in resp.json()["deadlines"]}
    assert {"acknowledgement", "resolution"} <= clocks


def test_unknown_persona_is_401() -> None:
    resp = _client().post(
        "/v1/cases", json={"case_type": "complaint"}, headers={"X-Dev-Persona": "ghost"}
    )
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region() -> None:
    body = _client().get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_workflows_lists_the_sample() -> None:
    body = _client().get("/v1/workflows").json()
    assert any(w["case_type"] == "complaint" for w in body)


def test_security_headers_present() -> None:
    headers = _client().get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_open_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert _client().post("/v1/audit/ping").status_code == 200


def test_s2s_rejects_missing_token_when_enforced(token_env: str) -> None:
    assert _client().post("/v1/audit/ping").status_code == 401


def test_s2s_accepts_correct_token(token_env: str) -> None:
    resp = _client().post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200
