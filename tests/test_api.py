"""API surface: verified-principal identity, four-eyes 403, cross-tenant 404, S2S, headers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from review_console.api.app import app

_TOKEN_ENV = "REVIEW_S2S_TOKEN"


def _client() -> TestClient:
    # An explicit LOOPBACK peer. The app object carries the exposure guard (see
    # ``tests/test_serving_path_exposure.py``), and Starlette's default test peer is the
    # non-loopback literal ``testclient``, which the guard correctly refuses. These cases are
    # about the API surface an operator reaches on their own machine, so say so.
    return TestClient(app, client=("127.0.0.1", 51234))


def _submit(client: TestClient, persona: str, *, severity: str = "medium") -> str:
    resp = client.post(
        "/v1/reviews",
        json={"action": "disburse", "subject": "Acme (FICTIONAL)", "severity": severity},
        headers={"X-Dev-Persona": persona},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["review_id"]


def test_submit_stamps_the_maker_from_the_principal() -> None:
    client = _client()
    resp = client.post(
        "/v1/reviews",
        json={"action": "disburse", "subject": "Acme (FICTIONAL)"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["maker"] == "demo.analyst@bank.example"
    assert body["tenant"] == "demo-bank"
    assert body["state"] == "pending"


def test_distinct_approver_can_approve() -> None:
    client = _client()
    review_id = _submit(client, "analyst", severity="medium")
    resp = client.post(
        f"/v1/reviews/{review_id}/decision",
        json={"disposition": "approve", "reason": "within limits"},
        headers={"X-Dev-Persona": "approver"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "allowed"
    assert body["item"]["state"] == "approved"


def test_self_approval_is_forbidden() -> None:
    client = _client()
    # The approver persona submits, then tries to approve their own item.
    review_id = _submit(client, "approver", severity="medium")
    resp = client.post(
        f"/v1/reviews/{review_id}/decision",
        json={"disposition": "approve", "reason": "self"},
        headers={"X-Dev-Persona": "approver"},
    )
    assert resp.status_code == 403
    assert "self_approval" in resp.json()["findings"]


def test_cross_tenant_get_is_404() -> None:
    client = _client()
    review_id = _submit(client, "analyst")
    # The other-tenant persona (other-bank) must not see a demo-bank item.
    resp = client.get(f"/v1/reviews/{review_id}", headers={"X-Dev-Persona": "other-tenant"})
    assert resp.status_code == 404


def test_unknown_persona_is_401() -> None:
    resp = _client().post(
        "/v1/reviews",
        json={"action": "x", "subject": "y"},
        headers={"X-Dev-Persona": "ghost"},
    )
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region() -> None:
    body = _client().get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_personas_feed_is_populated_locally() -> None:
    personas = _client().get("/v1/personas").json()
    ids = {p["id"] for p in personas}
    assert {"analyst", "approver"} <= ids


def test_security_headers_present() -> None:
    headers = _client().get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_endpoint_open_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert _client().post("/v1/audit/ping").status_code == 200


def test_s2s_endpoint_rejects_missing_token_when_enforced(token_env: str) -> None:
    assert _client().post("/v1/audit/ping").status_code == 401


def test_s2s_endpoint_accepts_correct_token(token_env: str) -> None:
    resp = _client().post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200


def _service_review_body() -> dict[str, object]:
    return {
        "action": "disburse_facility",
        "subject": "Acme Holdings (FICTIONAL)",
        "maker": "demo.analyst@bank.example",
        "tenant": "demo-bank",
        "source_key": "doc1:demo-bank:case-001:cdd_dossier",
        "severity": "medium",
    }


def test_service_intake_open_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    resp = _client().post("/v1/service/reviews", json=_service_review_body())
    assert resp.status_code == 201
    body = resp.json()
    # The maker + tenant come from the (trusted) body on the service path, not a persona.
    assert body["maker"] == "demo.analyst@bank.example"
    assert body["tenant"] == "demo-bank"


def test_service_intake_rejects_missing_token_when_enforced(token_env: str) -> None:
    resp = _client().post("/v1/service/reviews", json=_service_review_body())
    assert resp.status_code == 401


def test_service_intake_accepts_correct_token(token_env: str) -> None:
    resp = _client().post(
        "/v1/service/reviews",
        json=_service_review_body(),
        headers={"Authorization": f"Bearer {token_env}"},
    )
    assert resp.status_code == 201
    # The submitted review lands in that tenant's queue and can then be four-eyes reviewed.
    body = resp.json()
    assert body["state"] == "pending"
    assert body["source_key"] == "doc1:demo-bank:case-001:cdd_dossier"

    queue = _client().get("/v1/reviews", headers={"X-Dev-Persona": "approver"})
    assert queue.status_code == 200
    queued = next(item for item in queue.json() if item["review_id"] == body["review_id"])
    assert queued["source_key"] == "doc1:demo-bank:case-001:cdd_dossier"

