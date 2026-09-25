"""The half of the model-pill contract that lives in the BROWSER.

Every served console shows, at the top right of every page, the model that answered its last
request and ``Search`` when that answer used an online search tool (owner decision, 2026-09-23;
the pills replace the full-width provenance banner). The SERVICE half -- ``/healthz`` names the
runtime and the configured model, and responses carry ``X-Answered-By`` / ``X-Search-Used``
exposed to a cross-origin page -- is pinned in ``tests/unit/test_health_provenance.py`` and
``tests/unit/test_answer_provenance.py`` and is not restated here.

This file pins the other half, because the other half is the one that has broken before. On
2026-09-04 eight consoles were found to have been rendering NOTHING on every page load since the
banner landed: the component named ``/api/agent``, the same-origin route handler the service
template ships, in trees that ship no such handler. The health call reached a path nothing
serves, took the failure branch, and the failure branch renders nothing -- deliberately, because
chrome that guessed would assert provenance it does not have. A check that cannot fail loudly
fails as an ABSENCE, and an absent pill is exactly what no reviewer notices. Every service-side
assertion was true and green throughout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

UI = Path("ui")
PILLS = UI / "components" / "ModelPills.tsx"
WATCHER = UI / "lib" / "answer-provenance.mjs"

#: Build output and vendored packages are not this console's source.
_NOT_SOURCE = frozenset({"node_modules", ".next", "dist", "out", "coverage"})


def _console_sources() -> list[Path]:
    """Every ``.tsx`` this console actually ships, build output and vendored trees pruned."""
    found: list[Path] = []
    pending = [UI]
    while pending:
        for child in pending.pop().iterdir():
            if child.is_dir():
                if child.name not in _NOT_SOURCE:
                    pending.append(child)
            elif child.suffix == ".tsx":
                found.append(child)
    return sorted(found)


def test_the_pills_are_mounted_in_the_layout_rather_than_in_a_page() -> None:
    """Being on EVERY page is a property of the console, not of any page."""
    assert PILLS.is_file(), f"{PILLS} is missing, so no page states what answered"
    layout = UI / "app" / "layout.tsx"
    assert "<ModelPills />" in layout.read_text(), (
        "the root layout does not mount ModelPills, so the pills reach only the pages that "
        "remember to"
    )


def test_the_banner_is_gone_and_nothing_else_restates_the_model() -> None:
    """One component states the model. A leftover strip would phrase it a second way."""
    for source in _console_sources():
        text = source.read_text()
        assert "ProvenanceBanner" not in text, f"{source} still references the retired banner"
        assert "· model" not in text, f"{source} still renders the retired banner sentence"


def test_the_pills_read_healthz_through_the_base_this_console_actually_serves() -> None:
    """The defect that shipped, stated as an assertion.

    This console has no ``ui/app/api/agent`` proxy: the browser calls the service at the
    ``NEXT_PUBLIC_*`` base resolved once in ``ui/lib/api``. The pills must reach ``/healthz`` and
    watch responses through that same base; naming ``/api/agent`` here reaches nothing, and a base
    of their own would drift from the ``connect-src`` the console ships.
    """
    pills = PILLS.read_text()
    has_proxy = (UI / "app" / "api" / "agent").is_dir()
    assert ('"/api/agent"' in pills) == has_proxy, (
        "the pills name /api/agent but this console has no route handler there"
        if not has_proxy
        else "this console ships a /api/agent route handler but the pills do not use it"
    )
    if not has_proxy:
        assert re.search(r'from\s+"\.\./lib/api"', pills), "the pills must use lib/api's client"
        assert re.search(r"\bapi\s*\.health\(\)", pills), (
            "the pills must read /healthz through the shared client"
        )
        assert "watchAnswers(window, BASE_URL," in pills, (
            "the fetch watcher must match the base every other call in this console uses"
        )


def test_the_pills_read_both_answer_headers_through_one_watcher() -> None:
    watcher = WATCHER.read_text()
    assert '"x-answered-by"' in watcher and '"x-search-used"' in watcher
    assert "watchAnswers" in PILLS.read_text()
    # The watcher's own behaviour is proved in node, so that test must actually run in the gate.
    scripts = json.loads((UI / "package.json").read_text())["scripts"]
    assert "scripts/answer-provenance.test.mjs" in scripts["test"], (
        "npm test does not run the watcher's node test, so its behaviour is asserted by nothing"
    )


def test_a_proxy_if_one_exists_forwards_both_headers() -> None:
    """A same-origin proxy that copied only ``content-type`` would blank the answered pill.

    This console has none today; the check binds the day one is added.
    """
    for route in sorted((UI / "app").rglob("route.ts")):
        text = route.read_text()
        assert "x-answered-by" in text and "x-search-used" in text, (
            f"{route} proxies the service but does not forward the answer headers"
        )


#: Utility classes that move an element UP and out of the viewport.
_PULLS_UP = ("-mt-", "-my-", "-top-", "-inset-y-", "-inset-")


def test_the_pills_sit_at_the_top_right_where_a_reader_can_see_them() -> None:
    """A pill that renders off-screen has satisfied every other assertion in this file."""
    pills = PILLS.read_text()
    classes = set(re.findall(r"[-\w:./\[\]%()]+", pills))
    assert {"fixed", "right-[10px]", "top-[6px]"} <= classes, (
        "the pills are no longer pinned to the top right"
    )
    offenders = sorted(token for token in classes if token.startswith(_PULLS_UP))
    assert not offenders, f"the pills carry {offenders}, which pulls them above the viewport"
    # This console is light-only; a dark variant would invert the pills on a page that stays light.
    assert "color-scheme: light" in (UI / "app" / "globals.css").read_text()
    assert not [token for token in classes if token.startswith("dark:")]
