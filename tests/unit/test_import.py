"""Smoke test: the package imports and the CLI entry point exists."""

import thermalfea
from thermalfea import cli


def test_import() -> None:
    assert thermalfea.__name__ == "thermalfea"


def test_cli_main_returns_zero() -> None:
    assert cli.main([]) == 0
