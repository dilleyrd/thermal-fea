"""M2.2 — serialisation of the model (Data §3, §13)."""

from __future__ import annotations

import copy
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from thermalfea import api
from thermalfea.core import registry
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression, Function, Table
from thermalfea.core.units import UnitSettings
from thermalfea.materials.material import Material, PhaseChange
from thermalfea.model import bcs, geometry_ops, migrations
from thermalfea.model.model import InitialCondition, Model, RegionAssignment
from thermalfea.model.selections import Fingerprint, Selection
from thermalfea.model.serialize import from_json, to_json
from thermalfea.model.settings import MeshSettings, Refinement, SolutionSettings


def full_model() -> Model:
    """A model that uses every class of the data model."""
    g = geometry_ops
    fp_curve = Fingerprint(1, (0.3, 0.0, 0.0), 0.6, (0.0, 0.0, 0.0, 0.6, 0.0, 0.0))
    fp_surf = Fingerprint(2, (0.3, 0.5, 0.0), 0.6, (0.0, 0.0, 0.0, 0.6, 1.0, 0.0))
    fp_point = Fingerprint(0, (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    return Model(
        name="Everything",
        analysis="axisymmetric",
        display_units=UnitSettings(temperature="degC"),
        geometry=[
            g.Point("p1", 0.0, 0.0),
            g.Point("p2", 1.0, 0.0),
            g.Point("p3", 0.5, 0.5),
            g.Line("l1", "p1", "p2"),
            g.Arc("a1", "p2", "p3", "p1"),
            g.Spline("s1", ["p1", "p3", "p2"]),
            g.Rectangle("r1", 0.0, 0.0, 0.6, 1.0, corner_radius=0.05),
            g.Circle("c1", 0.3, 0.5, 0.1),
            g.Polygon("g1", [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
            g.SurfaceFromCurves("f1", ["l1", "a1"], holes=[["s1"]]),
            g.Boolean("b1", "cut", ["r1"], ["c1"]),
            g.Transform("t1", "rotate", ["b1"], {"angle": 0.5, "cx": 0.0, "cy": 0.0}, copy=True),
            g.ImportFile("i1", "part.step", "step", scale=0.001),
            g.Delete("d1", ["g1"]),
        ],
        selections={
            "bottom": Selection("bottom", 1, [1], [fp_curve]),
            "all": Selection("all", 2, [1], [fp_surf]),
            "corner": Selection("corner", 0, [1], [fp_point]),
        },
        materials={
            "steel": Material("steel", 50.0, 7800.0, 500.0),
            "alloy": Material(
                "alloy",
                Table([300.0, 400.0], [10.0, 12.0], "T", extrapolate="linear"),
                2700.0,
                Expression("900 + 0.1*T"),
                k2=3.0,
                phase_change=PhaseChange(800.0, 850.0, 4.0e5),
            ),
        },
        regions=[RegionAssignment("all", "steel", thickness=0.01, material_angle=0.3)],
        mesh_settings=MeshSettings(
            0.05, order=2, element_shape="quad", algorithm="frontal_quad",
            curve_sizes={"bottom": 0.01}, point_sizes={"corner": 0.002},
            curve_divisions={"bottom": 12}, structured_surfaces=["all"],
            refinements=[Refinement("bottom", 0.005, 0.05, 0.0, 0.2)], smoothing_passes=5,
        ),
        initial_condition=InitialCondition("per_region", per_region={"all": 350.0}),
        bcs=[
            bcs.FixedTemperature("base", "bottom", T=373.15),
            bcs.HeatFlux("flux", "bottom", q=Table([0.0, 10.0], [0.0, 5000.0], "t")),
            bcs.HeatFlow("flow", "bottom", P=12.0, active=False),
            bcs.HeatGeneration("gen", "all", Q=Expression("1e6*exp(-x)")),
            bcs.HeatPower("power", "all", P=100.0),
            bcs.Convection("conv", "bottom", h=750.0, T_inf=Expression("273.15 + 2*t")),
            bcs.CorrelationConvection(
                "nat", "bottom", correlation="vplate_natural", fluid="Air", T_inf=300.0,
                velocity=2.0, char_length=0.5, face_direction="up", wall_T_mode="average",
                multiplier=1.2,
            ),
            bcs.RadiationAmbient("rad", "bottom", emissivity=0.8, T_inf=300.0),
            bcs.Symmetry("sym", "bottom"),
            bcs.Adiabatic("adi", "bottom"),
        ],
        streams=[
            bcs.Stream(
                name="coolant", fluid="Water", mode="in_plane", walls=["bottom"],
                flow_area=1e-4, wetted_perimeter=0.04, cross_section="circular",
                roughness=1e-5, mass_flow=None, T_inlet=300.0,
                path=[(0.0, 0.0), (0.6, 0.0)], n_cells=10, nu_option="dittus_boelter",
                h_multiplier=0.9,
            ),
            bcs.Stream(
                name="through", fluid="Air", mode="through_plane", walls=["bottom"],
                flow_area=1e-3, wetted_perimeter=0.1, cross_section="square",
                mass_flow=Constant(0.01), T_inlet=Table([0.0, 5.0], [300.0, 320.0], "t"),
            ),
        ],
        network=bcs.FlowNetwork(
            nodes=[bcs.NetNode("in", pressure=2e5), bcs.NetNode("out", inflow=-0.1)],
            branches=[
                bcs.NetBranch("b1", "in", "out", kind="duct", length=0.6, stream="coolant"),
                bcs.NetBranch("b2", "in", "out", kind="loss", K_minor=1.5),
            ],
        ),
        enclosures=[
            bcs.Enclosure(
                "cavity",
                [bcs.EnclosureSurface("bottom", 0.8), bcs.EnclosureSurface("bottom", 0.5)],
                open_to_ambient=True, T_ambient=300.0,
            )
        ],
        contacts=[bcs.Contact("joint", "bottom", conductance=2000.0)],
        solution=SolutionSettings(
            kind="transient", end_time=120.0, initial_dt=0.5, dt_max=10.0, auto_timestep=False,
            max_dT_per_step=25.0, theta=0.5, lumped_capacitance=True, output="times",
            output_times=[10.0, 60.0, 120.0], max_iterations=50, line_search=False,
        ),
    )


def test_full_model_really_uses_every_class() -> None:
    model = full_model()
    assert {type(op) for op in model.geometry} == {
        registry.class_by_tag("geometry_op", t) for t in registry.tags("geometry_op")
    }
    assert {type(b) for b in model.bcs} == {registry.bc_info(t).cls for t in registry.bc_tags()}
    assert len(registry.bc_tags()) == 10 and len(registry.tags("geometry_op")) == 12


def test_round_trip_gives_an_equal_object() -> None:
    model = full_model()
    reference = copy.deepcopy(model)
    data = to_json(model)
    again = from_json(json.loads(json.dumps(data)))
    assert again == reference
    assert model == reference  # to_json did not change the model
    assert type(again.geometry[6]) is geometry_ops.Rectangle
    assert type(again.bcs[5]) is bcs.Convection
    assert isinstance(again.bcs[5].T_inf, Expression)
    assert again.selections["bottom"].fingerprints[0].center == (0.3, 0.0, 0.0)
    assert again.streams[0].path == [(0.0, 0.0), (0.6, 0.0)]
    assert again.geometry[8].vertices[1] == (1.0, 0.0)
    assert from_json(to_json(Model())) == Model()


def test_json_shape() -> None:
    data = to_json(full_model())
    assert data["schema_version"] == 1
    assert data["geometry"][0] == {"type": "point", "id": "p1", "x": 0.0, "y": 0.0}
    assert data["bcs"][0] == {
        "type": "fixed_temperature", "name": "base", "selection": "bottom", "active": True,
        "T": {"type": "constant", "value": 373.15},
    }
    assert data["bcs"][2]["active"] is False
    assert [op["type"] for op in data["geometry"]] == [
        "point", "point", "point", "line", "arc", "spline", "rectangle", "circle", "polygon",
        "surface_from_curves", "boolean", "transform", "import_file", "delete",
    ]
    assert data["materials"]["alloy"]["cp"] == {"type": "expression", "text": "900 + 0.1*T"}
    assert data["network"]["nodes"][0] == {"id": "in", "pressure": 2e5, "inflow": None}
    assert data["streams"][0]["mass_flow"] is None
    # nothing private leaks, and the data is plain JSON
    assert "_x" not in json.dumps(data) and "_tree" not in json.dumps(data)
    # a bare number is accepted wherever a function is expected (Data §1)
    data["bcs"][0]["T"] = 400
    assert from_json(data).bcs[0].T == Constant(400.0)


def test_save_and_load_are_stable(tmp_path: Path) -> None:
    model = full_model()
    first, second = tmp_path / "a.tfea", tmp_path / "b.tfea"
    api.save(model, first)
    loaded = api.load(first)
    assert loaded == model
    api.save(loaded, second)
    text = first.read_text(encoding="utf-8")
    assert text == second.read_text(encoding="utf-8")
    assert text.endswith("\n")
    # sorted keys and a 2-space indent
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"
    lines = text.splitlines()
    assert lines[1].startswith('  "analysis"')
    top_keys = [ln.split('"')[1] for ln in lines if ln.startswith('  "')]
    assert top_keys == sorted(top_keys)
    assert set(top_keys) == {f.name for f in dataclasses.fields(Model)}


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="cannot read"):
        api.load(tmp_path / "missing.tfea")
    bad = tmp_path / "bad.tfea"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelError, match="cannot read"):
        api.load(bad)
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ModelError, match="JSON object"):
        api.load(bad)


def test_schema_version_is_checked() -> None:
    data = to_json(Model())
    with pytest.raises(ModelError, match="newer version"):
        from_json({**data, "schema_version": 2})
    with pytest.raises(ModelError, match="schema_version"):
        from_json({k: v for k, v in data.items() if k != "schema_version"})
    with pytest.raises(ModelError, match="schema_version"):
        from_json({**data, "schema_version": "1"})
    with pytest.raises(ModelError, match="no migration"):
        from_json({**data, "schema_version": 0})


def test_older_file_is_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    assert migrations.MIGRATIONS == {}  # starts empty (Data §13)

    def v0_to_v1(d: dict) -> dict:
        d = dict(d)
        d["name"] = d.pop("title")
        return d

    monkeypatch.setitem(migrations.MIGRATIONS, 0, v0_to_v1)
    old = to_json(Model())
    del old["name"]
    old.update(schema_version=0, title="From version 0")
    snapshot = copy.deepcopy(old)
    model = from_json(old)
    assert model.name == "From version 0"
    assert model.schema_version == 1
    assert old == snapshot  # the input data is not modified


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("bcs", 0, "type"), "teleport", "unknown bc type"),
        (("geometry", 0, "type"), "hexagon", "unknown geometry_op type"),
        (("bcs", 0, "bogus"), 1, "unknown field"),
        (("geometry", 0, "x"), "left", "expected a number"),
        (("solution", "kind"), "quasi", "is not one of"),
        (("solution", "max_iterations"), 2.5, "expected an integer"),
        (("solution", "line_search"), 1, "expected true or false"),
        (("name",), 5, "expected a string"),
        (("geometry",), {}, "expected a list"),
        (("materials",), [], "expected an object"),
        (("mesh_settings",), None, "expected an object"),
        (("bcs", 0, "T"), {"type": "expression", "text": "__import__('os')"}, "not allowed"),
        (("selections", "bottom", "fingerprints", 0, "center"), [0.0, 1.0], "expected 3 values"),
    ],
)
def test_bad_data_raises_model_error(path: tuple, value: object, message: str) -> None:
    data = to_json(full_model())
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ModelError, match=message):
        from_json(data)


def test_missing_type_tag_and_missing_field() -> None:
    data = to_json(full_model())
    del data["bcs"][0]["type"]
    with pytest.raises(ModelError, match="missing 'type'"):
        from_json(data)
    data = to_json(full_model())
    del data["bcs"][0]["T"]
    with pytest.raises(ModelError, match="bcs"):
        from_json(data)
    # fields with defaults may be omitted (hand-written files)
    data = to_json(full_model())
    del data["bcs"][0]["active"]
    del data["solution"]
    model = from_json(data)
    assert model.bcs[0].active is True
    assert model.solution == SolutionSettings()


def test_new_bc_class_needs_no_serializer_change() -> None:
    """Plan §7 rule 6: registering a class is enough for it to be saved and loaded."""

    @dataclass
    class TestOnlyLoad(bcs.BoundaryCondition):
        strength: Function
        tags: list[int] = dataclasses.field(default_factory=list)

    registry.register_bc("test_only_load", TestOnlyLoad)
    try:
        model = Model(bcs=[TestOnlyLoad("x", "sel", strength=4, tags=[1, 2])])
        data = json.loads(json.dumps(to_json(model)))
        assert data["bcs"][0]["type"] == "test_only_load"
        again = from_json(data)
        assert again == model
        assert type(again.bcs[0]) is TestOnlyLoad
        assert registry.bc_info(TestOnlyLoad).term_factory is None
        registry.set_bc_term_factory("test_only_load", lambda bc: [])
        assert registry.bc_info("test_only_load").term_factory is not None
    finally:
        registry._CLASSES["bc"].pop("test_only_load")
        registry._BCS.pop("test_only_load")


def test_registry_family_errors() -> None:
    with pytest.raises(ModelError, match="unknown class family"):
        registry.register_class("nope", "x", int)
    with pytest.raises(ModelError, match="is not a"):
        registry.register_bc("wrong", geometry_ops.Point)
    with pytest.raises(ModelError, match="already used"):
        registry.register_bc("convection", bcs.HeatFlux)
    with pytest.raises(ModelError):
        registry.bc_info("nope")
    with pytest.raises(ModelError):
        registry.tag_of("bc", int)
    registry.register_bc("convection", bcs.Convection)  # re-registering the same class is fine
    assert registry.tag_of("bc", bcs.Convection) == "convection"
