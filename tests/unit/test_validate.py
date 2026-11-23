"""M3.8 — validation (Data §8): one test per check, each triggering it."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.materials.material import Material
from thermalfea.model import bcs
from thermalfea.model.model import InitialCondition, Model, RegionAssignment
from thermalfea.model.validate import Issue, errors, raise_if_errors, validate, validate_model


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


def test_stream_diameter_ratio_is_validated() -> None:
    model, built, mesh = good()
    st = bcs.Stream(
        name="s", fluid="Water", mode="in_plane", walls=["east"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="annulus_inner", T_inlet=300.0, mass_flow=0.1,
        diameter_ratio=0.5)
    model.streams.append(st)
    assert "stream-diameter-ratio" not in codes(validate(model, built, mesh))
    st.diameter_ratio = None
    issue = only(validate(model, built, mesh), "stream-diameter-ratio")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("stream", "s")
    assert "needs diameter_ratio" in issue.message
    st.diameter_ratio = 0.01
    message = only(validate(model, built, mesh), "stream-diameter-ratio").message
    assert "outside 0.05 to 1.0" in message
    st.cross_section, st.diameter_ratio = "circular", 0.5
    assert "annulus cross-sections only" in only(
        validate(model, built, mesh), "stream-diameter-ratio").message


# ============================================================ M11.23: validation coverage


def _stream(**changes: object) -> bcs.Stream:
    base: dict = dict(
        name="s", fluid="Water", mode="through_plane", walls=["east"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.1)
    return bcs.Stream(**{**base, **changes})


def _transient(model: Model) -> None:
    model.solution.kind = "transient"
    model.solution.end_time = 10.0


# ----------------------------------------------------------- selection dimensions (13b)


def test_selection_dimensions_come_from_the_registered_form() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.HeatFlux("flux", "L", q=10.0))  # a surface selection
    issue = only(validate(model, built, mesh), "wrong-selection")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("boundary condition", "flux")
    assert "curves" in issue.message
    model.bcs[-1] = bcs.HeatGeneration("gen", "west", Q=10.0)  # a curve selection
    issue = only(validate(model, built, mesh), "wrong-selection")
    assert issue.name == "gen" and "surfaces" in issue.message
    model.bcs[-1] = bcs.HeatPower("pow", "origin", P=10.0)  # a point selection
    assert "wrong-selection" in codes(validate(model, built, mesh))
    model.bcs[-1] = bcs.FixedTemperature("pin", "origin", T=350.0)  # a point is fine
    assert validate(model, built, mesh) == []
    model.bcs[-1] = bcs.HeatGeneration("gen", "L", Q=10.0)
    model.bcs.append(bcs.HeatFlux("flux", "bottom-left", q=10.0))
    assert validate(model, built, mesh) == []


# ------------------------------------------------------------ fluid names, any case (13c)


def test_fluid_names_are_case_insensitive() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.CorrelationConvection("nat", "east", "vplate_natural", "air", 300.0))
    model.streams.append(_stream(fluid="WATER"))
    assert "missing-fluid" not in codes(validate(model, built, mesh))
    model.streams[0].fluid = "WATTER"
    assert codes(validate(model, built, mesh)) == ["missing-fluid"]


# ------------------------------------------------------- NaN and non-finite properties (13e)


@pytest.mark.parametrize("text", ["sqrt(T - 400)", "0*T + log(-1)", "1/(T - 300)"])
def test_non_finite_material_property_is_an_error(text: str) -> None:
    model, built, mesh = good()
    model.materials["Silicon"].k = Expression(text)
    issue = only(validate(model, built, mesh), "non-finite-property")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("material", "Silicon")
    assert "conductivity" in issue.message and "not finite" in issue.message
    assert "bad-conductivity" not in codes(validate(model, built, mesh))  # reported once
    model.materials["Silicon"].k = Constant(100.0)
    assert validate(model, built, mesh) == []


@pytest.mark.parametrize("field", ["rho", "cp", "k2"])
def test_non_finite_property_is_checked_in_a_steady_model_too(field: str) -> None:
    model, built, mesh = good()
    setattr(model.materials["Silicon"], field, Expression("sqrt(T - 400)"))
    issue = only(validate(model, built, mesh), "non-finite-property")
    assert issue.name == "Silicon"


def test_nan_is_not_hidden_by_its_position_in_the_samples() -> None:
    model, built, mesh = good()
    # NaN only at the hot end of the sampled range: a plain min() would not see it
    model.bcs[0] = bcs.FixedTemperature("hot", "west", T=300.0)
    model.bcs[1] = bcs.Convection("cool", "east", h=100.0, T_inf=500.0)
    model.materials["Silicon"].k = Expression("where(T > 450, log(-1), 100)")
    assert "non-finite-property" in codes(validate(model, built, mesh))


# --------------------------------------------- material functions of temperature only (2.2)


@pytest.mark.parametrize(
    "fn", [Expression("200 + x"), Expression("200 + y"), Expression("200 + t"),
           Table([0.0, 10.0], [100.0, 200.0], "t")])
def test_material_property_may_depend_on_temperature_only(fn) -> None:
    model, built, mesh = good()
    model.materials["Silicon"].k = fn
    issue = only(validate(model, built, mesh), "material-not-temperature-only")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("material", "Silicon")
    assert "temperature only" in issue.message and "conductivity" in issue.message
    model.materials["Silicon"].k = Expression("200 + T/10")
    assert validate(model, built, mesh) == []


# ------------------------------------------------------------------------ streams (13g)


def test_a_valid_stream_has_no_issues() -> None:
    model, built, mesh = good()
    model.streams.append(_stream())
    assert validate(model, built, mesh) == []
    model.streams[0] = _stream(mode="in_plane", path=[(1.0, 0.0), (1.0, 0.5)], n_cells=4)
    assert validate(model, built, mesh) == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (dict(walls=["nope"]), "unknown-selection"),
        (dict(walls=["L"]), "wrong-selection"),
        (dict(flow_area=0.0), "bad-stream-geometry"),
        (dict(wetted_perimeter=float("nan")), "bad-stream-geometry"),
        (dict(h_multiplier=0.0), "bad-stream-multiplier"),
        (dict(roughness=-1e-5), "bad-stream-roughness"),
        (dict(n_cells=0), "bad-stream-cells"),
        (dict(mode="in_plane", path=None), "bad-stream-path"),
        (dict(mode="in_plane", path=[(0.0, 0.0)]), "bad-stream-path"),
        (dict(T_inlet=Expression("300 + 0*T")), "stream-temperature-dependence"),
        (dict(h_override=Expression("T")), "stream-temperature-dependence"),
        (dict(mass_flow=Expression("0.1 + 0*T")), "stream-temperature-dependence"),
        (dict(mass_flow=None), "stream-no-mass-flow"),
        (dict(mass_flow=0.0), "bad-mass-flow"),
        (dict(mass_flow=-0.1), "bad-mass-flow"),
        (dict(mass_flow=Table([0.0, 10.0], [0.1, -0.1], "t")), "bad-mass-flow"),
    ],
)
def test_stream_checks(changes: dict, code: str) -> None:
    model, built, mesh = good()
    _transient(model)  # the time table is sampled over the run
    model.streams.append(_stream(**changes))
    issue = only(validate(model, built, mesh), code)
    assert issue.severity == "error" and (issue.kind, issue.name) == ("stream", "s")


def test_duplicate_stream_names() -> None:
    model, built, mesh = good()
    model.streams += [_stream(), _stream()]
    issue = only(validate(model, built, mesh), "duplicate-name")
    assert (issue.kind, issue.name) == ("stream", "s")


def test_a_stream_on_a_network_branch_needs_no_mass_flow() -> None:
    model, built, mesh = good()
    model.streams.append(_stream(mass_flow=None))
    assert "stream-no-mass-flow" in codes(validate(model, built, mesh))
    model.network = bcs.FlowNetwork(
        [bcs.NetNode("a", pressure=1000.0), bcs.NetNode("b", pressure=0.0)],
        [bcs.NetBranch("x", "a", "b", length=1.0, stream="s")])
    assert validate(model, built, mesh) == []
    model.streams[0] = _stream(mass_flow=None, h_override=500.0)  # through-plane, given h
    model.network = None
    assert validate(model, built, mesh) == []


# ----------------------------------------------------------------------- network (13g)


@pytest.mark.parametrize(
    ("nodes", "branches", "name", "text"),
    [
        ([("a", 1.0, None), ("a", 0.0, None)], [("x", "a", "a", "duct", 1.0, 0.0, "s")],
         "a", "duplicate node"),
        ([("a", 1.0, None), ("b", 0.0, None)],
         [("x", "a", "b", "duct", 1.0, 0.0, "s"), ("x", "a", "b", "duct", 1.0, 0.0, "s")],
         "x", "duplicate branch"),
        ([("a", 1.0, 2.0), ("b", 0.0, None)], [("x", "a", "b", "duct", 1.0, 0.0, "s")],
         "a", "both a pressure and an inflow"),
        ([("a", None, 1.0), ("b", None, None)], [("x", "a", "b", "duct", 1.0, 0.0, "s")],
         "", "prescribed pressure"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "zz", "duct", 1.0, 0.0, "s")],
         "x", "unknown node"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "b", "duct", 1.0, 0.0, None)],
         "x", "no stream"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "b", "duct", 1.0, 0.0, "nope")],
         "x", "unknown stream"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "b", "duct", 0.0, 0.0, "s")],
         "x", "positive length"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "b", "loss", 0.0, 0.0, "s")],
         "x", "positive K_minor"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "a", "duct", 1.0, 0.0, "s")],
         "x", "to itself"),
        ([("a", 1.0, None), ("b", 0.0, None)], [("x", "a", "b", "duct", 1.0, -0.5, "s")],
         "x", "K_minor must not be negative"),
    ],
)
def test_network_checks(nodes, branches, name: str, text: str) -> None:
    model, built, mesh = good()
    model.streams.append(_stream(mass_flow=None))
    model.network = bcs.FlowNetwork(
        [bcs.NetNode(i, pressure=p, inflow=q) for i, p, q in nodes],
        [bcs.NetBranch(i, a, b, kind=k, length=n, K_minor=m, stream=s)
         for i, a, b, k, n, m, s in branches])
    found = [i for i in validate(model, built, mesh) if i.kind == "network"]
    issues = [i for i in found if text in i.message]
    assert issues, [i.message for i in found]
    assert issues[0].severity == "error" and issues[0].code == "bad-network"
    assert issues[0].name == name


def test_network_with_negative_roughness_names_the_branch() -> None:
    model, built, mesh = good()
    model.streams.append(_stream(mass_flow=None, roughness=-1e-4))
    model.network = bcs.FlowNetwork(
        [bcs.NetNode("a", pressure=1000.0), bcs.NetNode("b", pressure=0.0)],
        [bcs.NetBranch("x", "a", "b", length=1.0, stream="s")])
    issue = only(validate(model, built, mesh), "bad-network")
    assert issue.name == "x" and "roughness" in issue.message
    model.streams[0].roughness = 1e-4
    assert validate(model, built, mesh) == []


# -------------------------------------------------------------- initial condition (13g)


@pytest.mark.parametrize(
    ("ic", "text"),
    [
        (InitialCondition("uniform", value=None), "needs a value"),
        (InitialCondition("expression", value=Expression("300 + T")), "cannot depend on T"),
        (InitialCondition("per_region", per_region=None), "per_region"),
        (InitialCondition("per_region", per_region={}), "per_region"),
        (InitialCondition("per_region", per_region={"L": 300.0, "nope": 310.0}), "not a region"),
        (InitialCondition("per_region", per_region={"L": float("nan")}), "not finite"),
        (InitialCondition("from_results"), "results file"),
    ],
)
def test_initial_condition_checks(ic: InitialCondition, text: str) -> None:
    model, built, mesh = good()
    _transient(model)
    model.initial_condition = ic
    issue = [i for i in validate(model, built, mesh) if i.code == "bad-initial-condition"][0]
    assert issue.severity == "error"
    assert (issue.kind, issue.name) == ("model", "initial condition")
    assert text in issue.message
    model.solution.kind = "steady"  # a steady analysis has none
    assert "bad-initial-condition" not in codes(validate(model, built, mesh))


def test_valid_initial_conditions() -> None:
    model, built, mesh = good()
    _transient(model)
    for ic in (InitialCondition("uniform", value=Expression("300 + 10*x")),
               InitialCondition("per_region", per_region={"L": 300.0, "R": 310.0}),
               InitialCondition("from_results", results_path="results.h5")):
        model.initial_condition = ic
        assert "bad-initial-condition" not in codes(validate(model, built, mesh))


# ------------------------------------------------------------------------- contacts (13g)


def _contact(conductance, name: str = "gap") -> bcs.Contact:
    return bcs.Contact(name, "interface", conductance=conductance)


@pytest.mark.parametrize(
    "conductance",
    [0.0, -5.0, Expression("100 - 200*t/10"), Expression("1/(T - 300)"),
     Expression("sqrt(T - 400)"), Table([0.0, 10.0], [100.0, 0.0], "t"),
     Expression("-1 + 0*T")],
)
def test_contact_conductance_must_be_positive_and_finite(conductance) -> None:
    model, built, mesh = good()
    _transient(model)
    model.contacts.append(_contact(conductance))
    issue = only(validate(model, built, mesh), "bad-conductance")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("contact", "gap")


@pytest.mark.parametrize("conductance", [500.0, Expression("100 + T"), Expression("100 + x"),
                                         Table([0.0, 10.0], [100.0, 50.0], "t")])
def test_valid_contact_conductance(conductance) -> None:
    model, built, mesh = good()
    _transient(model)
    model.contacts.append(_contact(conductance))
    assert validate(model, built, mesh) == []


def test_duplicate_contact_names() -> None:
    model, built, mesh = good()
    model.contacts += [_contact(500.0), _contact(600.0)]
    issue = only(validate(model, built, mesh), "duplicate-name")
    assert (issue.kind, issue.name) == ("contact", "gap")


# --------------------------------------------------------------------- empty selections


def test_a_selection_without_entities_is_an_error_for_each_user() -> None:
    from thermalfea.model.selections import Selection

    model, built, mesh = good()
    model.selections["none-s"] = Selection("none-s", 2)
    model.selections["none-c"] = Selection("none-c", 1)
    model.regions.append(RegionAssignment("none-s", "Silicon"))
    model.bcs.append(bcs.HeatFlux("flux", "none-c", q=1.0))
    model.contacts.append(bcs.Contact("gap", "none-c", conductance=100.0))
    model.streams.append(_stream(walls=["none-c"]))
    found = {(i.kind, i.name) for i in validate(model, built, mesh) if i.code == "empty-selection"}
    assert found == {("region", "none-s"), ("boundary condition", "flux"), ("contact", "gap"),
                     ("stream", "s")}
    model.bcs[-1].active = False  # an inactive condition is not checked
    found = {i.kind for i in validate(model, built, mesh) if i.code == "empty-selection"}
    assert "boundary condition" not in found


# ------------------------------------------------------------------------ duplicate names


def test_duplicate_bc_names() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.Convection("cool", "bottom-left", h=10.0, T_inf=300.0))
    issue = only(validate(model, built, mesh), "duplicate-name")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("bc", "cool")


# ------------------------------------------------------------- D7: total loads, position


@pytest.mark.parametrize("x", ["x", "y", "100*x + t"])
def test_total_load_may_not_depend_on_position(x: str) -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.HeatPower("pow", "L", P=Expression(x)))
    model.bcs.append(bcs.HeatFlow("flow", "bottom-left", P=Expression(x)))
    found = [i for i in validate(model, built, mesh) if i.code == "position-dependent-total"]
    assert [(i.severity, i.kind, i.name) for i in found] == [("error", "bc", "pow"),
                                                             ("error", "bc", "flow")]
    assert "Heat Generation" in found[0].message and "Heat Flux" in found[1].message
    model.bcs[-2].P, model.bcs[-1].P = Expression("100 + t"), Constant(5.0)
    assert validate(model, built, mesh) == []


# ----------------------------------------------------------- D5, power law, velocity


@pytest.mark.parametrize("theta", [91.0, -100.0, float("nan"), float("inf")])
def test_inclination_outside_vertical_to_horizontal_is_an_error(theta: float) -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.CorrelationConvection(
        "inc", "east", "inclined_natural", "Air", 300.0, params={"theta_deg": theta}))
    issue = only(validate(model, built, mesh), "bad-inclination")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("bc", "inc")
    assert "hplate_up_natural" in issue.message
    model.bcs[-1].params["theta_deg"] = 75.0  # beyond the validity range: not refused here
    assert validate(model, built, mesh) == []


@pytest.mark.parametrize("params", [{"C": -1.0, "n": 0.25}, {"C": 2.0, "n": -0.25}])
def test_power_law_constants_must_not_be_negative(params: dict) -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.CorrelationConvection(
        "law", "east", "power_law", "Air", 300.0, params=params))
    issue = only(validate(model, built, mesh), "bad-power-law")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("bc", "law")
    model.bcs[-1].params = {"C": 2.0, "n": 0.25}
    assert validate(model, built, mesh) == []


def test_negative_velocity_is_an_error_when_sampled() -> None:
    model, built, mesh = good()
    model.bcs.append(bcs.CorrelationConvection(
        "forced", "east", "plate_forced_avg", "Air", 300.0, velocity=-2.0, char_length=0.5))
    issue = only(validate(model, built, mesh), "negative-velocity")
    assert issue.severity == "error" and (issue.kind, issue.name) == ("bc", "forced")
    model.bcs[-1].velocity = Expression("5 - t")
    _transient(model)
    assert "negative-velocity" in codes(validate(model, built, mesh))  # -5 at the end
    model.bcs[-1].velocity = Constant(3.0)
    assert validate(model, built, mesh) == []


# ------------------------------------------------------------- D8: validate_model


def test_validate_model_runs_the_checks_that_need_no_geometry() -> None:
    model, built, mesh = good()
    assert validate_model(model, mesh) == [] and validate_model(model) == []
    model.bcs.append(bcs.HeatFlux("flux", "L", q=1.0))  # surface selection
    model.materials["Silicon"].k = Expression("sqrt(T - 400)")
    _transient(model)
    model.solution.dt_min = 0.0
    model.streams.append(_stream(mass_flow=None))
    model.bcs.append(bcs.CorrelationConvection(
        "inc", "east", "inclined_natural", "Air", 300.0, params={"theta_deg": 95.0}))
    model.bcs.append(bcs.HeatPower("pow", "L", P=Expression("x")))
    model.initial_condition = InitialCondition("from_results")
    model.bcs.append(bcs.Convection("cool", "bottom-left", h=10.0, T_inf=300.0))
    model.contacts.append(_contact(-1.0))
    found = set(codes(validate_model(model, mesh), "error"))
    assert {"wrong-selection", "non-finite-property", "bad-time-step", "stream-no-mass-flow",
            "bad-inclination", "position-dependent-total", "bad-initial-condition",
            "duplicate-name", "bad-conductance"} <= found
    # the same errors are found with the built geometry
    assert found <= set(codes(validate(model, built, mesh), "error"))


def test_validate_model_skips_what_needs_a_built_geometry() -> None:
    from thermalfea.model.selections import Selection

    model, built, mesh = good()
    model.selections["none"] = Selection("none", 2)
    model.regions.append(RegionAssignment("none", "Silicon"))
    model.regions.pop(1)  # surface R has no region: needs the built surfaces
    assert validate_model(model, mesh) == []
    assert {"no-region", "empty-selection"} <= set(codes(validate(model, built, mesh)))
    model.regions[0].selection = "west"  # a curve selection: its dimension is stored
    assert "wrong-selection" in codes(validate_model(model))


def test_validate_model_axis_check_uses_the_mesh_box() -> None:
    model, built, mesh = good("axisymmetric", x0=0.2)
    assert validate_model(model, mesh) == []
    mesh.nodes[:, 0] -= 0.5  # nodes left of the axis
    assert "negative-radius" in codes(validate_model(model, mesh))
