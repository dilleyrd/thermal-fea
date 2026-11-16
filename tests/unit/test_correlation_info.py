"""M8.8: the display text of the correlations (formula, validity, inputs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermalfea.convection.correlation_info import CORRELATION_INFO, NOT_STATED
from thermalfea.convection.correlations import CORRELATIONS

THEORY = Path(__file__).resolve().parents[2] / "docs" / "theory.md"
#: Entries whose text is a table row of Theory §8 (the duct entry is assembled from §8.1).
TABLE_ROWS = [cid for cid in CORRELATIONS if cid != "duct_internal"]


def test_keys_equal_the_correlation_registry() -> None:
    assert set(CORRELATION_INFO) == set(CORRELATIONS)
    assert list(CORRELATION_INFO) == list(CORRELATIONS)  # table order


@pytest.mark.parametrize("cid", list(CORRELATIONS))
def test_strings_are_not_empty(cid: str) -> None:
    info = CORRELATION_INFO[cid]
    assert info.title.strip() and info.formula.strip() and info.validity.strip()
    assert info.length.strip() and info.source.strip()
    assert CORRELATIONS[cid].description.startswith(info.title)


def test_power_law_states_that_there_is_no_validity_range() -> None:
    assert CORRELATION_INFO["power_law"].validity == NOT_STATED
    assert "not stated" in NOT_STATED.lower()
    assert not CORRELATION_INFO["power_law"].needs_fluid
    assert all(i.needs_fluid for k, i in CORRELATION_INFO.items() if k != "power_law")


@pytest.mark.parametrize("cid", TABLE_ROWS)
def test_texts_are_the_words_of_the_theory_table(cid: str) -> None:
    rows = [line for line in THEORY.read_text(encoding="utf-8").splitlines() if f"`{cid}`" in line]
    assert rows, cid
    row = rows[0].replace("\\|", "|")
    info = CORRELATION_INFO[cid]
    assert info.formula in row
    if info.validity != NOT_STATED:
        assert info.validity in row


def test_inputs_are_inputs_of_the_calculator() -> None:
    from thermalfea.convection.calculator import _INPUT_KEYS

    for info in CORRELATION_INFO.values():
        assert set(info.inputs) <= _INPUT_KEYS
