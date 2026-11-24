"""User-library fluids are found by library.fluid() after the built-in ones (D12.5)."""

from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path

import numpy as np
import pytest
from handmade import make_problem

from thermalfea.core.errors import ModelError
from thermalfea.materials import library
from thermalfea.materials.material import Fluid
from thermalfea.model.bcs import CorrelationConvection, FixedTemperature
from thermalfea.solver.steady import steady_solution

LOGGER = "thermalfea.materials.library"


@pytest.fixture
def user_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "materials.json"
    monkeypatch.setattr(library, "user_library_path", lambda: path)
    return path


def _glycol() -> Fluid:
    return dataclasses.replace(library.fluid("Water"), name="Glycol mix")


def test_user_fluid_is_found_exactly_and_case_insensitively(user_path: Path) -> None:
    library.save_user_library({}, {"Glycol mix": _glycol()}, user_path)
    exact = library.fluid("Glycol mix")
    folded = library.fluid("GLYCOL MIX")
    assert exact.name == folded.name == "Glycol mix"
    assert exact == folded
    assert exact is not folded
    exact.name = "changed"  # an independent copy: the library keeps its own
    assert library.fluid("Glycol mix").name == "Glycol mix"


def test_built_in_fluid_is_still_found_first(user_path: Path) -> None:
    library.save_user_library({}, {"Glycol mix": _glycol()}, user_path)
    assert library.fluid("Water") == library.fluid("Water")
    assert library.fluid("water").name == "Water"


def test_model_with_a_user_fluid_gives_the_same_answer_as_water(user_path: Path) -> None:
    library.save_user_library({}, {"Glycol mix": _glycol()}, user_path)

    def solve(fluid_name: str) -> np.ndarray:
        bcs = (
            FixedTemperature("hot", "left", T=400.0),
            CorrelationConvection("conv", "right", "vplate_natural", fluid_name, 300.0,
                                  char_length=0.1),
        )
        problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1), bcs=bcs)
        result = steady_solution(problem)
        assert result.converged
        return result.T

    np.testing.assert_allclose(solve("Glycol mix"), solve("Water"), rtol=1e-12)


def test_user_fluid_with_a_built_in_name_is_not_used(
    user_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clash = Fluid.from_json({**library.fluid("Water").to_json(), "name": "water"})
    library.save_user_library({}, {"water": clash}, user_path)
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assert library.fluid("Water").name == "Water"
    assert library.fluid("WATER").name == "Water"
    # the user file is read only for a name the built-in fluids do not have
    with pytest.raises(ModelError):
        library.fluid("Unobtainium")
    with pytest.raises(ModelError):
        library.fluid("Unobtainium")  # cached: no second warning
    warnings = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "user fluid 'water' has the name of a built-in fluid" in message
    assert str(user_path) in message
    assert [n for n in library.fluid_names() if n.casefold() == "water"] == ["Water"]


def test_editing_the_file_is_picked_up(user_path: Path) -> None:
    library.save_user_library({}, {"Glycol mix": _glycol()}, user_path)
    assert library.fluid("Glycol mix").name == "Glycol mix"
    brine = dataclasses.replace(library.fluid("Water"), name="Brine")
    library.save_user_library({}, {"Brine": brine}, user_path)
    stamp = user_path.stat().st_mtime_ns + 1_000_000_000  # make the new mtime unambiguous
    os.utime(user_path, ns=(stamp, stamp))
    assert library.fluid("Brine").name == "Brine"
    with pytest.raises(ModelError, match="no fluid named 'Glycol mix'"):
        library.fluid("Glycol mix")


def test_unknown_name_lists_both_libraries(user_path: Path) -> None:
    library.save_user_library({}, {"Glycol mix": _glycol()}, user_path)
    with pytest.raises(ModelError) as info:
        library.fluid("Unobtainium")
    message = str(info.value)
    assert message.startswith("no fluid named 'Unobtainium' in the library")
    assert "Air, Ammonia" in message and "Water, Water Vapor (Steam)" in message
    assert message.endswith("; user library: Glycol mix)")


def test_missing_user_file_is_not_an_error(user_path: Path) -> None:
    assert not user_path.exists()
    assert library.fluid("Air").name == "Air"
    with pytest.raises(ModelError, match="user library: none"):
        library.fluid("Glycol mix")


def test_unreadable_user_file_only_matters_for_other_names(user_path: Path) -> None:
    user_path.write_text("{not json", encoding="utf-8")
    assert library.fluid("Water").name == "Water"
    with pytest.raises(ModelError, match="user material library"):
        library.fluid("Glycol mix")
