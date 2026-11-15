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
    "plate_forced_local": {"Pr": (0.6, None)},
    "cylinder_crossflow": {"RePr": (0.2, None)},
    "duct_internal": {"Pr": (0.5, 2000), "Re": (None, 5e6)},
    "vplate_natural": {},
    "inclined_natural": {"theta_deg": (None, 60)},
    "hplate_up_natural": {"Ra": (1e4, 1e11)},
    "hplate_down_natural": {"Ra": (1e5, 1e10)},
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
    assert len(c.check_validity(info, Ra=np.array([1e6, 1e5 - 1, 1e7]))) == 1
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
