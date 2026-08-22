from __future__ import annotations

import tomllib
from pathlib import Path

from review_console import __version__
from review_console.api.app import app


def test_package_api_and_project_versions_match() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["version"] == __version__ == app.version
