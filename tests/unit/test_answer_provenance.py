"""The service half of the model pill: which model ANSWERED, and whether it searched.

The console shows small pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever a model adapter NOTED as it
called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``.

This console binds no model port: routing, SLA clocks and quorum are deterministic and the
decision is a human's, so nothing is ever noted, no response carries either header, and the pill
keeps showing ``no-model``. The route is still proved to carry both headers the day something
notes, by standing a noting service in for the real one.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

# By module path: `review_console.api` re-exports the FastAPI object under the same name.
app_module = importlib.import_module("review_console.api.app")

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"
_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Chosen here, not inherited: `make portability` and CI run the suite with no profile
    # exported, and the seeded-persona adapter refuses to serve without one.
    monkeypatch.setenv("REVIEW_PROFILE", "local")
    return TestClient(app_module.app, client=("127.0.0.1", 51234))


def _submit(client: TestClient) -> Any:
    response = client.post(
        "/v1/reviews",
        json={"action": "disburse", "subject": "Acme (FICTIONAL)"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert response.status_code == 201, response.text
    return response


def test_a_human_review_route_names_no_model(client: TestClient) -> None:
    """Nothing noted, nothing sent: the pill never invents a model nobody called."""
    for response in (_submit(client), client.get("/healthz")):
        assert ANSWERED_BY not in response.headers
        assert SEARCH_USED not in response.headers


class _NotingConsole:
    """The real console service, plus what a model adapter that searched would note."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def submit(self, **kwargs: Any) -> Any:
        provenance.note_model("fake-answering-model")
        provenance.note_search()
        return self._real.submit(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def test_the_route_names_the_model_that_answered_and_that_it_searched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = app_module._console
    monkeypatch.setattr(app_module, "_console", lambda: _NotingConsole(real()))
    response = _submit(client)
    assert response.headers[ANSWERED_BY] == "fake-answering-model"
    assert response.headers[SEARCH_USED] == "true"
    # The console calls this service cross-origin, so the browser must be allowed to read both.
    exposed = response.headers["access-control-expose-headers"].lower()
    assert ANSWERED_BY in exposed and SEARCH_USED in exposed
    # The next request is a fresh record: an answer never leaks into a later response.
    monkeypatch.setattr(app_module, "_console", real)
    assert ANSWERED_BY not in _submit(client).headers


def test_the_pill_starts_from_no_model_because_nothing_here_calls_one(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["generator_model"] == "no-model"
    assert body["runtime"] == "local"


def test_no_hard_reasoning_flag_can_move_the_pill() -> None:
    """The fleet's latent false banner was a flag that moved the pill but not the model.

    This console never had the flag; this keeps it that way, so ``generator_model`` stays a
    statement about what is bound rather than about what a setting would swap in.
    """
    sources = sorted([*(_REPO / "src").rglob("*.py"), *(_REPO / "config").iterdir()])
    assert sources, "found nothing to scan, so this would pass by blindness"
    for source in sources:
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
