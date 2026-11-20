"""M10.6 — restart: a transient run continued from its last stored step.

The reference in every comparison is the same analysis run without interruption: a run
that is stopped and continued must give the same steps.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import h5py
import numpy as np
import pytest
from handmade import make_problem

from thermalfea.core.errors import ModelError
from thermalfea.model.bcs import Convection, FixedTemperature, RadiationAmbient
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post.results import Results
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.run import StepInfo, read_restart_state, run_steady, run_transient

T_INIT, END, DT = 300.0, 200.0, 10.0
LINEAR = (
    FixedTemperature("hot", "left", T=400.0),
    Convection("air", "right", h=200.0, T_inf=280.0),
)
NONLINEAR = (FixedTemperature("hot", "left", T=900.0),
             RadiationAmbient("rad", "right", emissivity=0.8, T_inf=300.0))


def slab(bcs=LINEAR, cells=(8, 2), **settings):
    """A slab heated at one end; the response time is several hundred seconds."""
    problem = make_problem("Q4", size=(0.1, 0.02), cells=cells, k=50.0, bcs=bcs)
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    defaults = dict(kind="transient", theta=0.5, initial_dt=DT, end_time=END,
                    auto_timestep=False)
    problem.settings = SolutionSettings(**{**defaults, **settings})
    return problem


def datasets(path: Path) -> dict[str, np.ndarray]:
    """Every per-step dataset of a results file."""
    out: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as f:
        for group in ("steps", "reactions"):
            f[group].visititems(
                lambda name, obj, g=group: out.__setitem__(f"{g}/{name}", obj[...])
                if isinstance(obj, h5py.Dataset) else None
            )
    return out


def assert_same_run(whole: Path, continued: Path, rtol: float) -> None:
    a, b = datasets(whole), datasets(continued)
    assert a.keys() == b.keys()
    for name in a:
        assert a[name].shape == b[name].shape, name
        if a[name].dtype.kind == "f":
            scale = float(np.nanmax(np.abs(a[name]))) if a[name].size else 0.0
            np.testing.assert_allclose(b[name], a[name], rtol=rtol, atol=rtol * scale,
                                       err_msg=name)
        else:
            np.testing.assert_array_equal(b[name], a[name], err_msg=name)


# ------------------------------------------------------- the same answer as one run


@pytest.mark.parametrize("theta", [0.5, 2.0 / 3.0, 1.0])
@pytest.mark.parametrize("output", ["all", "every_n"])
def test_continued_fixed_step_run_equals_the_uninterrupted_run(
    tmp_path: Path, theta: float, output: str
) -> None:
    extra = dict(theta=theta, output=output, output_every=4)
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    run_transient(slab(**extra), whole, T0=T_INIT)
    first = run_transient(slab(end_time=END * 0.4, **extra), part, T0=T_INIT)
    assert first.n_steps == 8
    second = run_transient(slab(**extra), part, restart=True)
    assert second.n_steps == 12 and second.times[0] == pytest.approx(END * 0.4)
    # the linear solve of each step is the same arithmetic: agreement to round-off
    assert_same_run(whole, part, rtol=1e-12)
    results = Results(part)
    assert results.times[-1] == pytest.approx(END)
    assert np.all(np.diff(results.times) > 0.0)


def test_continued_nonlinear_run_agrees_to_the_iteration_tolerance(tmp_path: Path) -> None:
    settings = dict(rtol=1e-10, ttol=1e-10)
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    run_transient(slab(NONLINEAR, **settings), whole, T0=T_INIT)
    run_transient(slab(NONLINEAR, end_time=END / 2, **settings), part, T0=T_INIT)
    run_transient(slab(NONLINEAR, **settings), part, restart=True)
    a, b = Results(whole), Results(part)
    np.testing.assert_allclose(b.times, a.times, rtol=1e-12)
    # g(T_n) is recomputed at the converged T_n instead of the last iterate
    np.testing.assert_allclose(b.temperature(-1), a.temperature(-1), rtol=1e-8)
    assert bool(np.all(b.converged))


def test_no_start_up_step_when_continuing(tmp_path: Path) -> None:
    """Crank-Nicolson starts with one theta = 1 step; a continued run must not repeat it."""
    part = tmp_path / "part.h5"
    start = run_transient(slab(end_time=END / 2), part, T0=T_INIT)
    assert start.thetas[0] == 1.0 and set(start.thetas[1:]) == {0.5}
    more = run_transient(slab(), part, restart=True)
    assert set(more.thetas) == {0.5}


def test_two_continuations(tmp_path: Path) -> None:
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    run_transient(slab(), whole, T0=T_INIT)
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    run_transient(slab(end_time=120.0), part, restart=True)
    run_transient(slab(), part, restart=True)
    assert_same_run(whole, part, rtol=1e-12)


def test_continuing_a_cancelled_run(tmp_path: Path) -> None:
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    run_transient(slab(), whole, T0=T_INIT)

    def progress(info: StepInfo) -> bool:
        return info.step < 7

    cancelled = run_transient(slab(), part, progress, T0=T_INIT)
    assert cancelled.cancelled and Results(part).n_steps == 8
    seen: list[int] = []
    run_transient(slab(), part, lambda info: seen.append(info.step) or True, restart=True)
    assert seen == list(range(8, 21))  # the step numbers carry on
    assert_same_run(whole, part, rtol=1e-12)


def test_automatic_stepping_continues_with_the_last_step_size(tmp_path: Path) -> None:
    auto = dict(auto_timestep=True, initial_dt=1.0, theta=1.0)
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    run_transient(slab(end_time=600.0, **auto), whole, T0=T_INIT)
    run_transient(slab(end_time=300.0, **auto), part, T0=T_INIT)
    before = Results(part)
    n_before, expected = before.n_steps, float(before.dt[-2:].max())
    problem = slab(end_time=600.0, **auto)
    assert read_restart_state(problem, part).dt == pytest.approx(expected)
    run_transient(problem, part, restart=True)
    after = Results(part)
    assert after.dt[n_before] == pytest.approx(expected)  # not the initial 1 s again
    assert after.times[-1] == pytest.approx(600.0)
    assert np.all(np.diff(after.times) > 0.0)
    # both are approximations within the time-stepping tolerance of the same history
    reference = Results(whole).temperature(-1)
    assert np.abs(after.temperature(-1) - reference).max() < 0.05  # K, of a 100 K rise


def test_the_file_is_updated_in_place(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    kept = Results(part).temperature(3).copy()
    run_transient(slab(), part, restart=True)
    results = Results(part)
    np.testing.assert_array_equal(results.temperature(3), kept)  # old steps untouched
    with h5py.File(part, "r") as f:
        assert '"end_time": 200.0' in f["meta"].attrs["settings"]  # the new settings


# ------------------------------------------------------------------------- refusals


def test_refusals(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    untouched = part.read_bytes()

    with pytest.raises(ModelError, match="results file not found"):
        run_transient(slab(), tmp_path / "missing.h5", restart=True)
    with pytest.raises(ModelError, match="already reach t = 50 s.*Set a later end time"):
        run_transient(slab(end_time=50.0), part, restart=True)
    with pytest.raises(ModelError, match="already reach"):
        run_transient(slab(end_time=20.0), part, restart=True)
    with pytest.raises(ModelError, match="different mesh"):
        run_transient(slab(cells=(10, 2)), part, restart=True)
    with pytest.raises(ModelError, match="different mesh"):  # same counts, other nodes
        other = slab()
        other.mesh.nodes[5, 0] += 1e-6
        run_transient(other, part, restart=True)
    assert part.read_bytes() == untouched  # a refused restart leaves the file alone

    steady = tmp_path / "steady.h5"
    problem = make_problem("Q4", size=(0.1, 0.02), cells=(8, 2), bcs=LINEAR)
    run_steady(problem, steady)
    with pytest.raises(ModelError, match="steady solution"):
        run_transient(slab(), steady, restart=True)

    garbage = tmp_path / "garbage.h5"
    garbage.write_text("not hdf5", encoding="utf-8")
    with pytest.raises(ModelError, match="not a results file"):
        run_transient(slab(), garbage, restart=True)

    bad = tmp_path / "bad.h5"
    shutil.copy(part, bad)
    with h5py.File(bad, "r+") as f:
        f["steps"]["converged"][-1] = False
    with pytest.raises(ModelError, match="did not converge"):
        run_transient(slab(), bad, restart=True)


def _rotate_connectivity(problem) -> None:
    conn = problem.mesh.blocks[0].conn
    conn[0] = np.roll(conn[0], 1)


def _change_region(problem) -> None:
    problem.mesh.blocks[0].region[3] += 1


def _flip_axisymmetric(problem) -> None:
    problem.mesh.axisymmetric = not problem.mesh.axisymmetric


def _change_facet(problem) -> None:
    problem.mesh.facets[0].entity[0] += 1


def _change_material(problem) -> None:
    r = next(iter(problem.regions.values()))
    r.material = replace(r.material, k=100.0)


def _change_thickness(problem) -> None:
    next(iter(problem.regions.values())).thickness *= 2.0


def _change_angle(problem) -> None:
    next(iter(problem.regions.values())).material_angle += 0.1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_rotate_connectivity, "different mesh.*connectivity"),
        (_change_region, "different mesh.*region"),
        (_flip_axisymmetric, "different mesh.*axisymmetric"),
        (_change_facet, "different mesh.*entity"),
        (_change_material, "material, thickness or material angle of region"),
        (_change_thickness, "material, thickness or material angle of region"),
        (_change_angle, "material, thickness or material angle of region"),
    ],
)
def test_incompatible_restart_is_refused_and_leaves_the_file_alone(
    tmp_path: Path, change, message: str
) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    untouched = part.read_bytes()
    other = slab()
    change(other)
    with pytest.raises(ModelError, match=message):
        run_transient(other, part, restart=True)
    assert part.read_bytes() == untouched


def test_changed_load_still_continues(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    bcs = (FixedTemperature("hot", "left", T=450.0),
           Convection("air", "right", h=300.0, T_inf=280.0))
    result = run_transient(slab(bcs), part, restart=True)
    assert result.times[-1] == pytest.approx(END)


def test_append_mode_of_the_writer_keeps_the_reaction_names(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(end_time=50.0), part, T0=T_INIT)
    with h5py.File(part, "r") as f:
        names = [f["reactions"][str(k)].attrs["name"] for k in range(len(f["reactions"]))]
    with ResultsWriter(part, slab(), append=True) as writer:
        assert writer.n_steps == 6 and writer._names == names
