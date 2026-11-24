"""M11.8 (Q26.4 f): a steady result shows "steady state", not "t = 0 s"; a transient its time.

The analysis of a results file is read from ``/meta`` ``analysis`` (``"planar, steady"``).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from handmade import make_problem

from thermalfea.core.units import UnitSettings
from thermalfea.model.bcs import FixedTemperature
from thermalfea.post.plots import contour, step_time_text
from thermalfea.post.results import Results
from thermalfea.post.summary import text_summary
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.steady import solve_steady


def _bcs():
    return (FixedTemperature("h", "left", T=400.0), FixedTemperature("c", "right", T=300.0))


def steady_file(path: Path) -> Results:
    problem = make_problem("T3", bcs=_bcs())
    T = solve_steady(problem)
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, T)
    return Results(path)


def transient_file(path: Path) -> Results:
    problem = make_problem("T3", bcs=_bcs())
    problem.settings = replace(problem.settings, kind="transient")
    T = solve_steady(make_problem("T3", bcs=_bcs()))
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, T)
        writer.append_step(12.5, T + 10.0)
    return Results(path)


def test_steady_result_is_labelled_steady_state(tmp_path: Path) -> None:
    results = steady_file(tmp_path / "s.h5")
    assert results.meta["analysis"].endswith("steady")
    assert step_time_text(results, 0.0, UnitSettings()) == "steady state"


def test_steady_contour_title_says_steady_state_not_a_time(tmp_path: Path) -> None:
    title = contour(steady_file(tmp_path / "s.h5"), step=-1).axes[0].get_title()
    assert "steady state" in title
    assert "t = 0" not in title and "0 s" not in title


def test_steady_summary_says_steady_state_not_a_time(tmp_path: Path) -> None:
    text = text_summary(steady_file(tmp_path / "s.h5"))
    steps_line = next(line for line in text.splitlines() if line.startswith("Steps stored:"))
    assert "steady state" in steps_line
    assert "t = " not in steps_line
    assert "t = 0" not in text


def test_transient_contour_title_still_shows_the_time(tmp_path: Path) -> None:
    results = transient_file(tmp_path / "t.h5")
    assert results.meta["analysis"].endswith("transient")
    assert "t = 12.5 s" in contour(results, step=-1).axes[0].get_title()
    assert "t = 0 s" in contour(results, step=0).axes[0].get_title()
    assert "steady" not in contour(results, step=-1).axes[0].get_title()


def test_transient_summary_still_shows_the_time(tmp_path: Path) -> None:
    text = text_summary(transient_file(tmp_path / "t.h5"))
    steps_line = next(line for line in text.splitlines() if line.startswith("Steps stored:"))
    assert "end at t = 12.5 s" in steps_line
    assert "summary at t = 12.5 s" in steps_line
    assert "steady" not in steps_line
