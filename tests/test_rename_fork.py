from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "rename_fork.py"
_SPEC = importlib.util.spec_from_file_location("rename_fork", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_OLD_CLI = _MODULE._OLD_CLI
_OLD_DIST = _MODULE._OLD_DIST
_OLD_ENV_PREFIX = _MODULE._OLD_ENV_PREFIX
_OLD_PACKAGE = _MODULE._OLD_PACKAGE
_OLD_RESOURCE = _MODULE._OLD_RESOURCE
_replacements = _MODULE._replacements
_rewrite_text = _MODULE._rewrite_text


def test_rename_rewrites_package_cli_env_and_resource() -> None:
    args = Namespace(
        package="zeta_review",
        cli="zeta-review",
        env_prefix="ZETA_REVIEW",
        resource="zeta-review-platform",
        dist="",
    )
    rewritten, count = _rewrite_text(
        f'{_OLD_PACKAGE} {_OLD_ENV_PREFIX}PROFILE {_OLD_CLI} name = "{_OLD_DIST}" {_OLD_RESOURCE}',
        _replacements(args),
    )
    assert count == 5
    assert rewritten == (
        "zeta_review ZETA_REVIEW_PROFILE zeta-review "
        'name = "zeta-review-platform" zeta-review-platform'
    )


def test_env_prefix_does_not_rewrite_prose_word() -> None:
    args = Namespace(
        package="zeta_review",
        cli="zeta-review",
        env_prefix="ZETA_REVIEW",
        resource="zeta-review-platform",
        dist="",
    )
    rewritten, _ = _rewrite_text(
        f"{_OLD_ENV_PREFIX}PROFILE {_OLD_ENV_PREFIX.lower()}workflow",
        _replacements(args),
    )
    assert rewritten == f"ZETA_REVIEW_PROFILE {_OLD_ENV_PREFIX.lower()}workflow"


def test_apply_preflights_destination_collision_before_any_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "src" / _OLD_PACKAGE
    destination = tmp_path / "src" / "zeta_review"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    config = tmp_path / "settings.py"
    config.write_text(f'PROFILE = "{_OLD_ENV_PREFIX}PROFILE"\n')

    monkeypatch.setattr(_MODULE, "_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename_fork.py",
            "--package",
            "zeta_review",
            "--cli",
            "zeta-review",
            "--env-prefix",
            "ZETA_REVIEW",
            "--resource",
            "zeta-review-platform",
            "--yes",
        ],
    )
    with pytest.raises(RuntimeError, match="destination package already exists"):
        _MODULE.main()
    assert config.read_text() == f'PROFILE = "{_OLD_ENV_PREFIX}PROFILE"\n'


def test_a_distribution_name_differing_from_the_resource_leaves_the_resource_alone() -> None:
    """They are the same token, so only the anchored form can tell them apart.

    Unanchored, the distribution replacement consumes every occurrence and the resource name
    silently becomes the distribution name. This proves that is absent, rather than believed.
    """
    args = Namespace(
        package="zeta_review",
        cli="zeta-review",
        env_prefix="ZETA_REVIEW",
        resource="zeta-review-platform",
        dist="zeta-review-dist",
    )
    rewritten, _ = _rewrite_text(
        f'{_OLD_RESOURCE} name = "{_OLD_DIST}"',
        _replacements(args),
    )

    assert rewritten == 'zeta-review-platform name = "zeta-review-dist"'
