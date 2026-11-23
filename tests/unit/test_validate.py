"""M3.8 — validation (Data §8): one test per check, each triggering it."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.materials.material import Material
from thermalfea.model import bcs
from thermalfea.model.model import InitialCondition, Model, RegionAssignment
from thermalfea.model.validate import Issue, errors, raise_if_errors, validate


def good(analysis: str = "planar", x0: float = 0.0) -> tuple[Model, object, object]:
    """A valid two-region model: no issues at all."""
    model = api.new_model(analysis)
    geo = api.Geometry(model)
    geo.rectangle(x0, 0.0, 0.4, 0.5, id="left")
    geo.rectangle(x0 + 0.4, 0.0, 0.6, 0.5, id="right")
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_surfaces(model, built, "L", where=lambda s: s.center[0] < x0 + 0.4)
    api.select_surfaces(model, built, "R", where=lambda s: s.center[0] > x0 + 0.4)
    api.select_curves(model, built, "bottom-left",
                      where=lambda c: abs(c.center[1]) < 1e-9 and c.center[0] < x0 + 0.4)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0] - x0) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - x0 - 1.0) < 1e-9)
    api.select_curves(model, built, "interface",
                      where=lambda c: abs(c.center[0] - x0 - 0.4) < 1e-9)
    api.select_points(model, built, "origin",
                      where=lambda p: abs(p.center[0] - x0) + abs(p.center[1]) < 1e-9)
    api.assign_region(model, "L", material="Copper (pure)")
    api.assign_region(model, "R", material="Silicon")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    return model, built, api.mesh(model, built)


def codes(issues: list[Issue], severity: str | None = None) -> list[str]:
    return [i.code for i in issues if severity is None or i.severity == severity]


def only(issues: list[Issue], code: str) -> Issue:
    (issue,) = [i for i in issues if i.code == code]
    return issue


def test_valid_model_has_no_issues() -> None:
    model, built, mesh = good()
    assert validate(model, built, mesh) == []
    assert validate(model, built) == []  # the mesh is optional
    raise_if_errors([])
    axi = good("axisymmetric", x0=0.2)
    assert validate(*axi) == []


# ------------------------------------------------------------------------------ regions


def test_surface_without_region() -> None:
    model, built, mesh = good()
    model.regions.pop()
    issue = only(validate(model, built, mesh), "no-region")
    assert issue.severity == "error" and issue.kind == "region"
    assert "has no region assignment" in issue.message and "surface" in issue.message


def test_surface_with_two_regions() -> None:
    model, built, mesh = good()
    model.regions.append(RegionAssignment("all", "Silicon"))
    issues = validate(model, built, mesh)
    assert codes(issues) == ["multiple-regions", "multiple-regions"]
    assert "'L', 'all'" in issues[0].message or "'R', 'all'" in issues[0].message


def test_missing_material() -> None:
    model, built, mesh = good()
    model.regions[0].material = "Unobtainium"
    issue = only(validate(model, built, mesh), "missing-material")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("region", "L")
    assert "'Unobtainium'" in issue.message


def test_missing_fluid() -> None:
    model, built, mesh = good()
    model.bcs.append(
        bcs.CorrelationConvection("nat", "east", "vplate_natural", "Unobtainium", 300.0)
    )
    model.streams.append(bcs.Stream(
        name="s", fluid="Oil", mode="through_plane", walls=["east"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.1))
    issues = validate(model, built, mesh)
    assert codes(issues) == ["missing-fluid", "missing-fluid"]
    assert [(i.kind, i.name) for i in issues] == [("bc", "nat"), ("stream", "s")]
    model.bcs[-1].fluid, model.streams[0].fluid = "Air", "Water"
    assert validate(model, built, mesh) == []
    # the user power law needs no fluid properties, so its fluid name is not checked
    model.bcs[-1] = bcs.CorrelationConvection(
        "law", "east", "power_law", "anything", 300.0, params={"C": 2.0, "n": 0.25})
    assert validate(model, built, mesh) == []


def test_region_with_bad_selection_or_thickness() -> None:
    model, built, mesh = good()
    model.regions[0].selection = "west"  # curves, not surfaces
    assert "wrong-selection" in codes(validate(model, built, mesh))
    model, built, mesh = good()
    model.regions[0].selection = "nope"
    assert "unknown-selection" in codes(validate(model, built, mesh))
    model, built, mesh = good()
    model.regions[0].thickness = 0.0
    assert codes(validate(model, built, mesh)) == ["bad-thickness"]


# --------------------------------------------------------------------------- selections


def test_stale_selection() -> None:
    model, built, _ = good()
    model.geometry[0].height = 0.25  # the left rectangle shrinks: its curves change
    rebuilt = api.build(model)
    issues = validate(model, rebuilt, api.mesh(model, rebuilt))
    stale = [i for i in issues if i.code == "stale-selection"]
    assert stale and all(i.severity == "error" and i.kind == "selection" for i in stale)
    assert {"L", "west", "interface"} <= {i.name for i in stale}
    assert all(f"'{i.name}' is stale" in i.message for i in stale)
    # a stale selection is reported once, not again by everything that uses it
    assert codes(issues).count("stale-selection") == len(stale)
    assert "unknown-selection" not in codes(issues)


def test_bc_with_unknown_or_wrong_selection() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.HeatFlux("flux", "missing", q=1.0))
    issue = only(validate(model, built, mesh), "unknown-selection")
    assert (issue.kind, issue.name) == ("boundary condition", "flux")
    model.bcs[-1] = bcs.FixedTemperature("fix", "L", T=300.0)  # a surface selection
    issue = only(validate(model, built, mesh), "wrong-selection")
    assert "points or curves" in issue.message
    model.bcs[-1].active = False  # inactive conditions are not checked
    assert validate(model, built, mesh) == []


def test_curve_with_two_fixed_temperatures() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.FixedTemperature("again", "west", T=350.0))
    issue = only(validate(model, built, mesh), "double-fixed-temperature")
    assert issue.severity == "error" and "'hot', 'again'" in issue.message
    # a fixed point at the end of a fixed curve is not "two BCs on a curve"
    model.bcs[-1] = bcs.FixedTemperature("pin", "origin", T=350.0)
    assert validate(model, built, mesh) == []


# -------------------------------------------------------------------------- physics


def test_steady_without_temperature_reference() -> None:
    model, built, mesh = good()
    model.bcs[:] = [bcs.HeatFlux("in", "west", q=10.0), bcs.HeatFlux("out", "east", q=-10.0)]
    issue = only(validate(model, built, mesh), "no-temperature-reference")
    assert issue.severity == "error" and "temperature reference" in issue.message
    for reference in (
        bcs.FixedTemperature("f", "west", T=300.0),
        bcs.Convection("c", "west", h=1.0, T_inf=300.0),
        bcs.RadiationAmbient("r", "west", emissivity=0.5, T_inf=300.0),
        bcs.CorrelationConvection("n", "west", "vplate_natural", "Air", 300.0),
    ):
        model.bcs.append(reference)
        assert "no-temperature-reference" not in codes(validate(model, built, mesh))
        model.bcs.pop()
    model.bcs.append(bcs.FixedTemperature("off", "west", T=300.0, active=False))
    assert "no-temperature-reference" in codes(validate(model, built, mesh))
    model.bcs.pop()
    model.streams.append(bcs.Stream(
        name="s", fluid="Water", mode="in_plane", walls=["east"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.1))
    assert "no-temperature-reference" not in codes(validate(model, built, mesh))
    model.streams.clear()
    model.solution.kind = "transient"  # a transient analysis has its initial condition
    assert "no-temperature-reference" not in codes(validate(model, built, mesh))


def test_radiation_with_a_non_absolute_temperature() -> None:
    model, built, mesh = good()
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=27.0)
    assert validate(model, built, mesh) == []  # 27 K is odd but absolute
    model.bcs[1].T_inf = Expression("-20")
    issue = only(validate(model, built, mesh), "non-absolute-temperature")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("bc", "rad")
    assert "Celsius" in issue.message
    model.bcs[1].T_inf = Expression("300")
    model.bcs[0].T = Expression("0")  # another temperature of the model at 0 K
    assert only(validate(model, built, mesh), "non-absolute-temperature").name == "hot"
    # without radiation a temperature <= 0 is not an error
    model.bcs[1] = bcs.Convection("cool", "east", h=100.0, T_inf=-20.0)
    assert errors(validate(model, built, mesh)) == []


def test_transient_needs_positive_capacity_and_end_time() -> None:
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.solution.end_time = 0.0
    issue = only(validate(model, built, mesh), "bad-end-time")
    assert issue.severity == "error" and issue.kind == "solution"
    model.solution.end_time = 10.0
    assert validate(model, built, mesh) == []
    model.materials["Silicon"] = Material("Silicon", 148.0, 0.0, 712.0)
    issue = only(validate(model, built, mesh), "bad-capacity")
    assert (issue.kind, issue.name) == ("material", "Silicon") and "density" in issue.message
    model.materials["Silicon"] = Material(
        "Silicon", 148.0, 2330.0, Table([300.0, 400.0], [700.0, -1.0], "T"))
    assert "specific heat" in only(validate(model, built, mesh), "bad-capacity").message
    model.solution.kind = "steady"  # rho and cp do not matter in a steady analysis
    assert errors(validate(model, built, mesh)) == []
    model.materials["Silicon"] = Material("Silicon", -1.0, 2330.0, 712.0)
    assert only(validate(model, built, mesh), "bad-conductivity").severity == "error"


def test_axisymmetric_node_with_negative_radius() -> None:
    model, built, mesh = good("axisymmetric", x0=-0.2)
    issue = only(validate(model, built, mesh), "negative-radius")
    assert issue.severity == "error" and issue.kind == "mesh" and "radius" in issue.message
    assert "negative-radius" not in codes(validate(model, built, None))  # needs the mesh
    on_axis = good("axisymmetric", x0=0.0)
    assert validate(*on_axis) == []
    planar = good("planar", x0=-0.2)
    assert validate(*planar) == []


def test_property_table_not_covering_the_temperature_range_is_a_warning() -> None:
    model, built, mesh = good()  # the model's temperatures span 300 .. 400 K
    table = Table([320.0, 380.0], [140.0, 120.0], "T")
    model.materials["Silicon"] = Material("Silicon", table, 2330.0, 712.0)
    issues = validate(model, built, mesh)
    assert codes(issues) == ["table-range"] and errors(issues) == []
    issue = issues[0]
    assert issue.severity == "warning" and (issue.kind, issue.name) == ("material", "Silicon")
    assert "320 to 380 K" in issue.message and "300 to 400 K" in issue.message
    assert "held" in issue.message
    raise_if_errors(issues)  # warnings do not block the solve
    wide = Table([250.0, 500.0], [150.0, 100.0], "T", extrapolate="linear")
    model.materials["Silicon"] = Material("Silicon", wide, 2330.0, 712.0)
    assert validate(model, built, mesh) == []
    # an unused material is not checked
    model.materials["spare"] = Material("spare", table, 1.0, 1.0)
    assert validate(model, built, mesh) == []


def test_contact_must_be_an_interface_between_two_regions() -> None:
    model, built, mesh = good()
    model.contacts.append(bcs.Contact("joint", "interface", conductance=2000.0))
    assert validate(model, built, mesh) == []
    model.contacts[0].selection = "west"  # an outer boundary: one region only
    issue = only(validate(model, built, mesh), "contact-not-interface")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("contact", "joint")
    assert "borders 1 region" in issue.message
    model.contacts[0].selection = "L"
    assert "wrong-selection" in codes(validate(model, built, mesh))


def test_initial_condition_temperatures_count_in_a_transient_analysis() -> None:
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=300.0)
    model.initial_condition = InitialCondition("uniform", value=-5.0)
    issue = only(validate(model, built, mesh), "non-absolute-temperature")
    assert issue.name == "initial condition"
    model.initial_condition = InitialCondition("per_region", per_region={"L": 300.0, "R": 0.0})
    assert "of R" in only(validate(model, built, mesh), "non-absolute-temperature").name


def test_raise_if_errors_lists_every_error() -> None:
    model, built, mesh = good()
    model.regions.pop()
    model.bcs.append(bcs.HeatFlux("flux", "missing", q=1.0))
    issues = validate(model, built, mesh)
    assert len(errors(issues)) == 2
    with pytest.raises(ModelError, match="2 error") as info:
        raise_if_errors(issues)
    assert "no region assignment" in str(info.value) and "'missing'" in str(info.value)


def test_features_without_a_solver_term_are_refused_not_ignored() -> None:
    """Enclosures (M9) and phase change (M10.2) exist in the model but not in the solver."""
    from thermalfea.materials.material import PhaseChange
    from thermalfea.solver.compile import compile as compile_problem

    model, built, mesh = good()
    model.enclosures.append(bcs.Enclosure("cavity", [bcs.EnclosureSurface("east", 0.8)]))
    issue = only(validate(model, built, mesh), "not-implemented")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("enclosure", "cavity")
    assert "not available in this version" in issue.message
    with pytest.raises(ModelError, match="surface-to-surface radiation is not available"):
        compile_problem(model, built, mesh)  # also without validation (api.solve without built)
    with pytest.raises(ModelError, match="not available in this version"):
        api.solve(model, mesh)

    model, built, mesh = good()
    copper = model.materials["Copper (pure)"]
    copper.phase_change = PhaseChange(T_sol=1350.0, T_liq=1360.0, latent_heat=2.0e5)
    issue = only(validate(model, built, mesh), "not-implemented")
    assert (issue.kind, issue.name) == ("material", "Copper (pure)")
    with pytest.raises(ModelError, match="phase change"):
        compile_problem(model, built, mesh)
    # a material with a phase change that no region uses does not matter
    model, built, mesh = good()
    model.materials["spare"] = Material("spare", 1.0, 1.0, 1.0,
                                        phase_change=PhaseChange(300.0, 310.0, 1.0e5))
    assert "not-implemented" not in codes(validate(model, built, mesh))


# ------------------------------------------------------------------- time stepping settings


def transient_good() -> tuple[Model, object, object]:
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.solution.end_time = 10.0
    return model, built, mesh


@pytest.mark.parametrize(("field", "value"), [
    ("dt_max", 0.0),
    ("dt_max", -1.0),
    ("dt_max", float("nan")),
    ("dt_max", 1e-12),  # below dt_min (default 1e-9)
    ("initial_dt", 0.0),
    ("initial_dt", -1.0),
    ("initial_dt", float("nan")),
    ("dt_min", 0.0),
    ("dt_min", -1.0),
    ("dt_min", float("nan")),
    ("time_tol", 0.0),
    ("time_tol", -0.02),
    ("max_dT_per_step", 0.0),
    ("max_dT_per_step", -5.0),
])
def test_transient_time_step_settings_must_be_positive(field: str, value: float) -> None:
    model, built, mesh = transient_good()
    setattr(model.solution, field, value)
    errs = errors(validate(model, built, mesh))
    assert errs and all(i.kind == "solution" and i.code == "bad-time-step" for i in errs)
    assert any(field in i.message for i in errs)
    with pytest.raises(ModelError):
        raise_if_errors(validate(model, built, mesh))


@pytest.mark.parametrize("field", ["rtol", "ttol"])
def test_nonlinear_tolerances_must_be_positive_in_steady_and_transient(field: str) -> None:
    for kind in ("steady", "transient"):
        model, built, mesh = good()
        model.solution.kind = kind
        setattr(model.solution, field, 0.0)
        errs = errors(validate(model, built, mesh))
        assert [(i.code, i.kind) for i in errs] == [("bad-tolerance", "solution")]
        assert field in errs[0].message


def test_valid_time_step_settings_give_no_issues() -> None:
    model, built, mesh = transient_good()
    assert validate(model, built, mesh) == []
    model.solution.dt_max = 1.0
    model.solution.initial_dt = 0.5
    model.solution.max_dT_per_step = 5.0
    model.solution.dt_min = 1e-6
    assert validate(model, built, mesh) == []


def test_time_step_settings_of_a_steady_model_are_not_checked() -> None:
    model, built, mesh = good()  # steady: the time-stepping fields are not used
    model.solution.dt_max = -1.0
    model.solution.initial_dt = 0.0
    model.solution.time_tol = 0.0
    assert validate(model, built, mesh) == []


# ------------------------------------------------ M11.15: position and time in temperatures


def _absolute(model: Model, built: object, mesh: object) -> list[str]:
    return [i.name for i in validate(model, built, mesh) if i.code == "non-absolute-temperature"]


@pytest.mark.parametrize("with_mesh", [True, False])
def test_position_dependent_ambient_is_sampled_where_it_applies(with_mesh: bool) -> None:
    model, built, mesh = good()
    mesh = mesh if with_mesh else None
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=Expression("300*x"))
    assert _absolute(model, built, mesh) == []  # east is at x = 1 m: 300 K, not 0 K
    model.bcs[1] = bcs.RadiationAmbient("rad", "west", emissivity=0.8, T_inf=Expression("300*x"))
    assert _absolute(model, built, mesh) == ["rad"]  # west is at x = 0: 0 K, refused as before


def test_position_dependent_fixed_temperature_with_radiation() -> None:
    model, built, mesh = good()
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=300.0)
    model.bcs[0] = bcs.FixedTemperature("hot", "east", T=Expression("300*x"))
    assert _absolute(model, built, mesh) == []
    model.bcs[0] = bcs.FixedTemperature("hot", "west", T=Expression("300*x"))
    assert _absolute(model, built, mesh) == ["hot"]


def test_constant_zero_kelvin_is_still_refused() -> None:
    model, built, mesh = good()
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=0.0)
    assert _absolute(model, built, mesh) == ["rad"]


def test_position_dependent_value_without_points_is_unknown() -> None:
    model, built, mesh = good()
    model.bcs[1] = bcs.RadiationAmbient("rad", "nowhere", emissivity=0.8,
                                        T_inf=Expression("300*x"))
    found = validate(model, built, mesh)
    assert "unknown-selection" in codes(found)  # reported for the selection, not as 0 K
    assert "non-absolute-temperature" not in codes(found)


def test_position_dependent_initial_condition_needs_the_mesh_nodes() -> None:
    """The whole domain is sampled at the mesh nodes; without a mesh it is unknown (the
    corners of the bounding box could lie outside the shape)."""
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=300.0)
    model.initial_condition = InitialCondition("expression", value=Expression("300*x"))
    assert _absolute(model, built, mesh) == ["initial condition"]  # 0 K on the west edge
    assert _absolute(model, built, None) == []  # no points: unknown, never blocks


@pytest.mark.parametrize(("end_time", "refused"), [(100.0, True), (10.0, False)])
def test_time_table_is_sampled_over_the_run(end_time: float, refused: bool) -> None:
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.solution.end_time = end_time
    drop = Table([0.0, 50.0], [300.0, 0.0], "t")
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8, T_inf=drop)
    assert (_absolute(model, built, mesh) == ["rad"]) is refused


def test_time_expression_is_sampled_at_start_and_end() -> None:
    model, built, mesh = good()
    model.solution.kind = "transient"
    model.solution.end_time = 100.0
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.8,
                                        T_inf=Expression("300 - 3*t"))
    assert _absolute(model, built, mesh) == ["rad"]  # 0 K at the end of the run
    model.solution.end_time = 10.0
    assert _absolute(model, built, mesh) == []
