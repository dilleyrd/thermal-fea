"""M2.1 — model dataclasses (Data §3, §4, §5, §8, §10)."""

from __future__ import annotations

import copy
import dataclasses

import pytest

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.core.units import UnitSettings, from_si, to_si
from thermalfea.model import bcs, geometry_ops
from thermalfea.model.model import InitialCondition, Model, RegionAssignment
from thermalfea.model.selections import Fingerprint, Selection
from thermalfea.model.settings import MeshSettings, Refinement, SolutionSettings


def test_default_model() -> None:
    m = Model()
    assert (m.schema_version, m.name, m.analysis) == (1, "Untitled", "planar")
    assert not m.axisymmetric
    assert Model(analysis="axisymmetric").axisymmetric
    assert m.display_units == UnitSettings()
    for name in ("geometry", "regions", "bcs", "streams", "enclosures", "contacts"):
        assert getattr(m, name) == []
    assert m.selections == {} and m.materials == {}
    assert m.network is None
    assert m.solution == SolutionSettings()
    assert m.mesh_settings.global_size > 0
    assert m.initial_condition.kind == "uniform"
    assert Model() == Model()
    # defaults are not shared between instances
    m.bcs.append(bcs.Adiabatic("a", "s"))
    assert Model().bcs == []
    with pytest.raises(ModelError):
        Model(analysis="3d")  # type: ignore[arg-type]


def test_solution_settings_defaults_match_data_model() -> None:
    s = SolutionSettings()
    expected = dict(
        kind="steady", end_time=1.0, initial_dt=None, dt_min=1e-9, dt_max=None,
        auto_timestep=True, time_tol=0.02, max_dT_per_step=None, theta=1.0,
        lumped_capacitance=False, output="all", output_every=1, output_times=[],
        rtol=1e-6, ttol=1e-4, max_iterations=30, line_search=True,
    )
    assert dataclasses.asdict(s) == expected
    for bad in (dict(kind="x"), dict(output="x"), dict(theta=0.0), dict(theta=1.5),
                dict(output_every=0), dict(max_iterations=0)):
        with pytest.raises(ModelError):
            SolutionSettings(**bad)


def test_mesh_settings() -> None:
    s = MeshSettings(global_size=0.05)
    assert (s.order, s.element_shape, s.algorithm, s.smoothing_passes) == (1, "tri", "frontal", 3)
    assert s.curve_sizes == {} and s.refinements == []
    full = MeshSettings(
        0.1, order=2, element_shape="quad", algorithm="frontal_quad",
        curve_sizes={"c": 0.01}, point_sizes={"p": 0.005}, curve_divisions={"c": 8},
        structured_surfaces=["s"], refinements=[Refinement("c", 0.01, 0.1, 0.0, 0.2)],
    )
    assert full.refinements[0].size_min == 0.01
    for bad in (dict(global_size=0.0), dict(global_size=1.0, order=3),
                dict(global_size=1.0, element_shape="hex"),
                dict(global_size=1.0, algorithm="magic")):
        with pytest.raises(ModelError):
            MeshSettings(**bad)


def test_geometry_ops() -> None:
    ops = [
        geometry_ops.Point("p1", 0.0, 0.0),
        geometry_ops.Point("p2", 1.0, 0.0),
        geometry_ops.Line("l1", "p1", "p2"),
        geometry_ops.Arc("a1", "p1", "p2", "p1"),
        geometry_ops.Spline("s1", ["p1", "p2"]),
        geometry_ops.Rectangle("r1", 0.0, 0.0, 0.6, 1.0),
        geometry_ops.Circle("c1", 0.3, 0.5, 0.1),
        geometry_ops.Polygon("g1", [(0, 0), (1, 0), (0, 1)]),
        geometry_ops.SurfaceFromCurves("f1", ["l1", "a1"]),
        geometry_ops.Boolean("b1", "cut", ["r1"], ["c1"]),
        geometry_ops.Transform("t1", "translate", ["b1"], {"dx": 1.0, "dy": 0.0}),
        geometry_ops.ImportFile("i1", "part.step", "step"),
        geometry_ops.Delete("d1", ["g1"]),
    ]
    assert all(isinstance(op, geometry_ops.GeometryOp) for op in ops)
    assert len({op.id for op in ops}) == len(ops)
    assert ops[5].corner_radius == 0.0
    assert ops[7].vertices == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    assert ops[8].holes == []
    assert ops[10].copy is False
    assert ops[11].scale == 1.0
    for bad in (
        lambda: geometry_ops.Point("", 0, 0),
        lambda: geometry_ops.Boolean("b", "xor", [], []),
        lambda: geometry_ops.Transform("t", "shear", [], {}),
        lambda: geometry_ops.ImportFile("i", "p", "iges"),
    ):
        with pytest.raises(ModelError):
            bad()


def test_selection_and_fingerprint() -> None:
    fp = Fingerprint(1, (0.5, 0, 0), 1, (0, 0, 0, 1, 0, 0))
    assert fp.center == (0.5, 0.0, 0.0)
    assert fp.bbox == (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    sel = Selection("bottom", 1, [3], [fp])
    assert sel.tags == [3]
    assert Selection("empty", 2).tags == []
    with pytest.raises(ModelError):
        Selection("bad", 1, [1, 2], [fp])
    with pytest.raises(ModelError):
        Selection("bad", 2, [1], [fp])
    with pytest.raises(ModelError):
        Selection("", 1)
    with pytest.raises(ModelError):
        Fingerprint(1, (0.0, 0.0), 1.0, (0, 0, 0, 1, 0, 0))


def test_boundary_conditions() -> None:
    fixed = bcs.FixedTemperature("base", "bottom", T=373.15)  # the call in Data §11
    assert fixed.T == Constant(373.15)
    assert fixed.active is True
    assert bcs.FixedTemperature("b", "s", 300.0, active=False).active is False
    conv = bcs.Convection("c", "s", h=Expression("10 + T/100"), T_inf=300)
    assert conv.h.depends_on_T and conv.T_inf == Constant(300.0)
    items = [
        fixed, conv,
        bcs.HeatFlux("q", "s", q=5000.0),
        bcs.HeatFlow("p", "s", P=10.0),
        bcs.HeatGeneration("g", "s", Q=1e6),
        bcs.HeatPower("w", "s", P=Table([0.0, 1.0], [0.0, 5.0], "t")),
        bcs.RadiationAmbient("r", "s", emissivity=0.8, T_inf=300.0),
        bcs.Symmetry("sym", "s"),
        bcs.Adiabatic("adi", "s"),
        bcs.CorrelationConvection("cc", "s", correlation="vplate_natural", fluid="Air",
                                  T_inf=300.0),
    ]
    assert all(isinstance(b, bcs.BoundaryCondition) for b in items)
    cc = items[-1]
    assert (cc.velocity, cc.char_length, cc.face_direction) == (None, None, None)
    assert (cc.wall_T_mode, cc.multiplier) == ("local", 1.0)
    assert bcs.CorrelationConvection("c", "s", "x", "Air", 300, velocity=2).velocity == Constant(2)
    with pytest.raises(ModelError):
        bcs.CorrelationConvection("c", "s", "x", "Air", 300.0, wall_T_mode="mean")
    with pytest.raises(ModelError):
        bcs.CorrelationConvection("c", "s", "x", "Air", 300.0, face_direction="sideways")
    with pytest.raises(ModelError):
        bcs.FixedTemperature("", "s", 300.0)
    with pytest.raises(ModelError):
        bcs.FixedTemperature("b", "s", "hot")  # type: ignore[arg-type]
    assert copy.deepcopy(conv) == conv


def test_enclosure_contact_stream_network() -> None:
    enc = bcs.Enclosure("e", [bcs.EnclosureSurface("a", 0.8), bcs.EnclosureSurface("b", 0.5)],
                        open_to_ambient=True, T_ambient=300)
    assert enc.T_ambient == Constant(300.0)
    assert bcs.Enclosure("e", []).T_ambient is None
    assert bcs.Contact("c", "iface", 2000).conductance == Constant(2000.0)
    stream = bcs.Stream(
        name="s", fluid="Water", mode="in_plane", walls=["w"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300, mass_flow=0.1,
        path=[(0, 0), (1, 0)],
    )
    assert stream.T_inlet == Constant(300.0) and stream.mass_flow == Constant(0.1)
    assert stream.path == [(0.0, 0.0), (1.0, 0.0)]
    assert (stream.roughness, stream.n_cells, stream.nu_option, stream.h_multiplier) == (
        0.0, None, "auto", 1.0)
    base = dict(name="s", fluid="Water", walls=[], flow_area=1.0, wetted_perimeter=1.0,
                T_inlet=300.0)
    with pytest.raises(ModelError):
        bcs.Stream(mode="sideways", cross_section="circular", **base)
    with pytest.raises(ModelError):
        bcs.Stream(mode="in_plane", cross_section="star", **base)
    net = bcs.FlowNetwork(
        nodes=[bcs.NetNode("n1", pressure=1e5), bcs.NetNode("n2", inflow=-0.1)],
        branches=[bcs.NetBranch("b1", "n1", "n2", length=2.0, stream="s")],
    )
    assert net.branches[0].kind == "duct" and net.branches[0].K_minor == 0.0
    with pytest.raises(ModelError):
        bcs.NetBranch("b", "a", "c", kind="valve")


def test_region_and_initial_condition() -> None:
    r = RegionAssignment("all", "Copper (pure)")
    assert (r.thickness, r.material_angle) == (1.0, 0.0)
    assert InitialCondition("uniform", value=300).value == Constant(300.0)
    assert InitialCondition("per_region", per_region={"a": 300.0}).value is None
    assert InitialCondition("from_results", results_path="old.h5").results_path == "old.h5"
    with pytest.raises(ModelError):
        InitialCondition("random")  # type: ignore[arg-type]


def test_units() -> None:
    k, c, f = UnitSettings(), UnitSettings(temperature="degC"), UnitSettings(temperature="degF")
    assert to_si(300.0, "temperature", k) == 300.0
    assert to_si(100.0, "temperature", c) == pytest.approx(373.15)
    assert to_si(212.0, "temperature", f) == pytest.approx(373.15)
    assert to_si(18.0, "temperature_difference", f) == pytest.approx(10.0)
    assert to_si(10.0, "temperature_difference", c) == 10.0
    for s in (k, c, f):
        for q in ("temperature", "temperature_difference", "length", "power"):
            assert from_si(to_si(12.5, q, s), q, s) == pytest.approx(12.5)
    assert to_si(2.0, "htc", f) == 2.0
    with pytest.raises(ModelError):
        to_si(1.0, "luminosity", k)
    with pytest.raises(ModelError):
        UnitSettings(temperature="R")  # type: ignore[arg-type]
    with pytest.raises(ModelError):
        UnitSettings(length="ft")  # type: ignore[arg-type]
