"""M6.2 — convection correlations: registry, validity, errors, continuity (Theory §8, §8.1)."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from thermalfea.convection import correlations as c
from thermalfea.core.errors import ModelError

IDS = [
    "plate_forced_avg",
    "plate_forced_local",
    "cylinder_crossflow",
    "duct_internal",
    "vplate_natural",
    "inclined_natural",
    "hplate_up_natural",
    "hplate_down_natural",
    "hcyl_natural",
    "power_law",
]

VALIDITY = {
    "plate_forced_avg": {"Pr": (0.6, None), "Re": (None, 1e8)},
    "plate_forced_local": {"Pr": (0.6, None), "Re": (None, 1e8)},
    "cylinder_crossflow": {"RePr": (0.2, None)},
    "duct_internal": {"Pr": (0.5, 2000), "Re": (None, 5e6)},
    "vplate_natural": {},
    "inclined_natural": {"theta_deg": (None, 60)},
    "hplate_up_natural": {"Ra": (1e4, 1e11)},
    "hplate_down_natural": {"Ra": (1e4, 1e9), "Pr": (0.7, None)},
    "hcyl_natural": {"Ra": (None, 1e12)},
    "power_law": {},
}


def test_registry_has_ten_ids_in_table_order() -> None:
    assert list(c.CORRELATIONS) == IDS
    for key, info in c.CORRELATIONS.items():
        assert info.id == key


@pytest.mark.parametrize("key", IDS)
def test_registry_function_and_inputs(key: str) -> None:
    info = c.CORRELATIONS[key]
    assert callable(info.function)
    params = inspect.signature(info.function).parameters
    assert info.inputs
    for name in info.inputs:
        assert name in params


@pytest.mark.parametrize("key", IDS)
def test_registry_validity_matches_table(key: str) -> None:
    assert c.CORRELATIONS[key].validity == VALIDITY[key]


def test_check_validity_inside_range_no_message() -> None:
    info = c.CORRELATIONS["hplate_up_natural"]
    assert c.check_validity(info, Ra=1e6) == []
    assert c.check_validity(info, Ra=np.array([1e4, 1e5, 1e11])) == []


def test_check_validity_one_message_per_violated_quantity() -> None:
    info = c.CORRELATIONS["plate_forced_avg"]
    msgs = c.check_validity(info, Pr=0.5, Re=2e8)
    assert len(msgs) == 2
    assert any("Pr" in m for m in msgs)
    assert any("Re" in m for m in msgs)


def test_check_validity_array_any_element_violates() -> None:
    info = c.CORRELATIONS["hplate_down_natural"]
    assert len(c.check_validity(info, Ra=np.array([1e6, 1e4 - 1, 1e7]))) == 1
    assert c.check_validity(info, Ra=np.array([1e6, 1e7])) == []


def test_check_validity_repr_key() -> None:
    info = c.CORRELATIONS["cylinder_crossflow"]
    assert c.check_validity(info, RePr=0.2) == []
    assert len(c.check_validity(info, RePr=0.1)) == 1


def test_check_validity_theta_key() -> None:
    info = c.CORRELATIONS["inclined_natural"]
    assert c.check_validity(info, theta_deg=60.0) == []
    assert len(c.check_validity(info, theta_deg=75.0)) == 1


def test_check_validity_ignores_unsupplied_and_unrestricted() -> None:
    info = c.CORRELATIONS["vplate_natural"]
    assert c.check_validity(info, Ra=1e20, Pr=1e-9) == []
    info = c.CORRELATIONS["hcyl_natural"]
    assert c.check_validity(info, Ra=1e13) != []
    assert c.check_validity(info, Pr=1e9) == []


def test_unknown_cross_section_raises() -> None:
    with pytest.raises(ModelError):
        c.nu_laminar("hexagon")
    with pytest.raises(ModelError):
        c.nu_duct(1000.0, 0.7, cross_section="hexagon")


def test_unknown_wall_raises() -> None:
    with pytest.raises(ModelError):
        c.nu_laminar("circular", "constant_power")


def test_unknown_option_raises() -> None:
    with pytest.raises(ModelError):
        c.nu_duct(1e5, 0.7, option="petukhov")


def test_nu_duct_continuous_at_transition_end_points() -> None:
    eps = 1e-9
    for Re_k in (c.RE_LAMINAR, c.RE_TURBULENT):
        lo = c.nu_duct(Re_k - eps, 0.7)
        hi = c.nu_duct(Re_k + eps, 0.7)
        assert lo == pytest.approx(hi, rel=1e-6)


def test_nu_duct_continuous_both_options() -> None:
    for option in ("auto", "dittus_boelter"):
        for Re_k in (c.RE_LAMINAR, c.RE_TURBULENT):
            lo = c.nu_duct(Re_k - 1e-9, 0.7, option=option)
            hi = c.nu_duct(Re_k + 1e-9, 0.7, option=option)
            assert lo == pytest.approx(hi, rel=1e-6)


def test_nu_duct_vectorised_over_all_regimes() -> None:
    Re = np.array([100.0, 2300.0, 3000.0, 4000.0, 2e4, 1e5])
    Pr = np.full_like(Re, 0.7)
    got = c.nu_duct(Re, Pr)
    assert got.shape == Re.shape
    assert np.all(np.isfinite(got))
    for i in range(Re.size):
        assert got[i] == pytest.approx(c.nu_duct(float(Re[i]), 0.7), rel=1e-12)


def test_correlations_module_imports_no_model_mesh_solver_materials() -> None:
    src = Path(c.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "thermalfea.model",
        "thermalfea.core.mesh",
        "thermalfea.solver",
        "thermalfea.materials",
    ):
        assert forbidden not in src


# ---------------------------------------------------------------- M11.38 validity rules


def n_msgs(key: str, **values: float | np.ndarray) -> int:
    return len(c.check_validity(c.CORRELATIONS[key], **values))


@pytest.mark.parametrize("key", ["plate_forced_avg", "plate_forced_local"])
def test_plate_forced_pr_lower_bound_always(key: str) -> None:
    for Re in (1e3, 1e6):
        assert n_msgs(key, Re=Re, Pr=0.6) == 0
        assert n_msgs(key, Re=Re, Pr=0.59) == 1


@pytest.mark.parametrize("key", ["plate_forced_avg", "plate_forced_local"])
def test_plate_forced_pr_upper_bound_only_when_turbulent(key: str) -> None:
    assert n_msgs(key, Re=5e5, Pr=100.0) == 0  # laminar branch: no upper Pr bound
    assert n_msgs(key, Re=5e5 + 1, Pr=60.0) == 0
    msgs = c.check_validity(c.CORRELATIONS[key], Re=1e6, Pr=60.1)
    assert len(msgs) == 1 and "Pr" in msgs[0] and "Re > 500000.0" in msgs[0]
    # array: one point turbulent with a large Pr is enough
    assert n_msgs(key, Re=np.array([1e3, 1e6]), Pr=np.array([100.0, 0.7])) == 0
    assert n_msgs(key, Re=np.array([1e3, 1e6]), Pr=np.array([0.7, 100.0])) == 1


@pytest.mark.parametrize("key", ["plate_forced_avg", "plate_forced_local"])
def test_plate_forced_re_upper_bound(key: str) -> None:
    assert n_msgs(key, Re=1e8, Pr=0.7) == 0
    assert n_msgs(key, Re=1e8 * 1.01, Pr=0.7) == 1


def test_hplate_up_pr_bound_only_below_1e7() -> None:
    key = "hplate_up_natural"
    assert n_msgs(key, Ra=1e6, Pr=0.7) == 0
    assert n_msgs(key, Ra=1e6, Pr=0.69) == 1
    assert n_msgs(key, Ra=1e7, Pr=0.69) == 1  # Ra <= 1e7 includes 1e7
    assert n_msgs(key, Ra=1e7 + 1, Pr=0.01) == 0
    assert n_msgs(key, Ra=1e11, Pr=0.7) == 0
    assert n_msgs(key, Ra=1e11 * 1.01, Pr=0.7) == 1
    assert n_msgs(key, Ra=1e4 - 1, Pr=0.7) == 1


def test_hplate_down_ranges() -> None:
    key = "hplate_down_natural"
    assert n_msgs(key, Ra=1e4, Pr=0.7) == 0
    assert n_msgs(key, Ra=1e9, Pr=0.7) == 0
    assert n_msgs(key, Ra=1e4 - 1, Pr=0.7) == 1
    assert n_msgs(key, Ra=1e9 * 1.01, Pr=0.7) == 1
    assert n_msgs(key, Ra=1e6, Pr=0.69) == 1
    assert n_msgs(key, Ra=1e11, Pr=0.7) == 1  # above the new 1e9 bound


def test_duct_dittus_boelter_bounds_only_when_selected() -> None:
    info = c.CORRELATIONS["duct_internal"]
    db = c.DITTUS_BOELTER_BOUNDS
    assert c.check_validity(info, extra_bounds=db, Re=2e4, Pr=0.6) == []
    assert c.check_validity(info, extra_bounds=db, Re=2e4, Pr=160.0) == []
    assert len(c.check_validity(info, extra_bounds=db, Re=2e4, Pr=161.0)) == 1
    assert len(c.check_validity(info, extra_bounds=db, Re=2e4, Pr=0.45)) == 2  # + Gnielinski
    assert len(c.check_validity(info, extra_bounds=db, Re=5e3, Pr=1.0)) == 1  # Re < 1e4
    assert c.check_validity(info, extra_bounds=db, Re=1e4, Pr=1.0) == []
    assert c.check_validity(info, Re=5e3, Pr=1.0) == []  # not selected
    assert c.check_validity(info, extra_bounds=db, Re=1e3, Pr=1.0) == []  # laminar


def test_inclined_face_messages() -> None:
    f = c.inclined_face_messages
    assert len(f("up", 50.0)) == 1  # top face of a hot plate
    assert f("up", -50.0) == []  # top face of a cold plate
    assert len(f("down", -50.0)) == 1  # bottom face of a cold plate
    assert f("down", 50.0) == []
    assert f(None, 50.0) == [] and f(None, -50.0) == []
    assert len(f("up", np.array([-5.0, 5.0]))) == 1
