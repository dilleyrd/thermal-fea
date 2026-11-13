"""M1.7 — functions for load and property values (Data §1)."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import (
    Constant,
    Expression,
    Function,
    Table,
    as_function,
    function_from_json,
    function_to_json,
)

# ---------------------------------------------------------------------------- Constant


def test_constant() -> None:
    f = Constant(5)
    assert isinstance(f, Function)
    assert f() == 5.0
    assert isinstance(f(), float)
    assert f(t=3.0, x=1.0, y=2.0, T=300.0) == 5.0
    out = f(x=np.zeros((4, 3)))
    assert out.shape == (4, 3)
    assert np.all(out == 5.0)
    assert (f.depends_on_T, f.depends_on_time) == (False, False)
    assert f.breakpoints() == []
    assert Constant(5) == Constant(5.0)
    for bad in ("5", None, True, float("nan"), float("inf")):
        with pytest.raises(ModelError):
            Constant(bad)


# ------------------------------------------------------------------------------- Table


def test_table_interpolation() -> None:
    f = Table([0.0, 10.0, 20.0], [100.0, 200.0, 150.0], "t")
    assert isinstance(f, Function)
    assert f(t=0.0) == 100.0
    assert f(t=5.0) == pytest.approx(150.0)
    assert f(t=10.0) == 200.0
    assert f(t=15.0) == pytest.approx(175.0)
    assert f(t=20.0) == 150.0
    assert isinstance(f(t=5.0), float)


def test_table_hold_extrapolation() -> None:
    f = Table([0.0, 10.0, 20.0], [100.0, 200.0, 150.0], "t")
    assert f.extrapolate == "hold"
    assert f(t=-50.0) == 100.0
    assert f(t=1e9) == 150.0


def test_table_linear_extrapolation() -> None:
    f = Table([0.0, 10.0, 20.0], [100.0, 200.0, 150.0], "t", extrapolate="linear")
    assert f(t=-5.0) == pytest.approx(50.0)  # slope +10 per unit below the table
    assert f(t=30.0) == pytest.approx(100.0)  # slope -5 per unit above the table
    assert f(t=5.0) == pytest.approx(150.0)  # unchanged inside
    assert f(t=0.0) == 100.0
    assert f(t=20.0) == 150.0
    single = Table([3.0], [7.0], "t", extrapolate="linear")
    assert single(t=-1.0) == 7.0
    assert single(t=10.0) == 7.0


def test_table_against_temperature_is_vectorised() -> None:
    f = Table([300.0, 400.0], [10.0, 20.0], "T", extrapolate="linear")
    temps = np.array([[250.0, 300.0], [350.0, 450.0]])
    np.testing.assert_allclose(f(T=temps), [[5.0, 10.0], [15.0, 25.0]])
    held = Table([300.0, 400.0], [10.0, 20.0], "T")
    np.testing.assert_allclose(held(T=temps), [[10.0, 10.0], [15.0, 20.0]])
    # time is ignored by a temperature table; x gives the output its shape
    assert f(t=123.0, T=350.0) == pytest.approx(15.0)
    assert f(x=np.zeros(5), T=350.0).shape == (5,)


def test_table_flags_and_breakpoints() -> None:
    time_table = Table([0.0, 10.0, 20.0], [1.0, 2.0, 3.0], "t")
    assert (time_table.depends_on_time, time_table.depends_on_T) == (True, False)
    assert time_table.breakpoints() == [0.0, 10.0, 20.0]
    temp_table = Table([300.0, 400.0], [1.0, 2.0], "T")
    assert (temp_table.depends_on_time, temp_table.depends_on_T) == (False, True)
    assert temp_table.breakpoints() == []


def test_table_validation() -> None:
    for args in (
        ([0.0, 1.0], [1.0], "t"),
        ([], [], "t"),
        ([0.0, 0.0], [1.0, 2.0], "t"),
        ([1.0, 0.0], [1.0, 2.0], "t"),
        ([0.0, 1.0], [1.0, 2.0], "x"),
        ([0.0, 1.0], [1.0, float("nan")], "t"),
        ([0.0, "a"], [1.0, 2.0], "t"),
    ):
        with pytest.raises(ModelError):
            Table(*args)
    with pytest.raises(ModelError):
        Table([0.0, 1.0], [1.0, 2.0], "t", extrapolate="cubic")


# -------------------------------------------------------------------------- Expression


def test_expression_scalar() -> None:
    f = Expression("500 + 20*sin(2*pi*t/60)")
    assert isinstance(f, Function)
    assert f(t=0.0) == pytest.approx(500.0)
    assert f(t=15.0) == pytest.approx(520.0)
    assert isinstance(f(t=15.0), float)
    assert Expression("2**3 - 7 % 4 + -1")() == pytest.approx(8 - 3 - 1)
    assert Expression("e")() == pytest.approx(np.e)
    assert Expression(" 1/4 ")() == 0.25


def test_expression_vectorised_over_arrays() -> None:
    f = Expression("x**2 + 3*y - T/100 + t")
    x = np.linspace(0.0, 1.0, 12).reshape(3, 4)
    y = np.linspace(2.0, 3.0, 12).reshape(3, 4)
    temp = np.full((3, 4), 300.0)
    out = f(t=2.0, x=x, y=y, T=temp)
    assert out.shape == (3, 4)
    np.testing.assert_allclose(out, x**2 + 3 * y - 3.0 + 2.0)
    # broadcasting between arguments, and a constant expression takes the array shape
    assert f(x=np.zeros((3, 1)), y=np.zeros(4)).shape == (3, 4)
    const = Expression("7")(x=x)
    assert const.shape == (3, 4)
    assert np.all(const == 7.0)


def test_expression_functions_and_comparisons() -> None:
    x = np.array([-2.0, -0.5, 0.5, 2.0])
    np.testing.assert_allclose(Expression("where(x > 0, 10, 20)")(x=x), [20, 20, 10, 10])
    np.testing.assert_allclose(Expression("where(-1 < x <= 0.5, 1, 0)")(x=x), [0, 1, 1, 0])
    np.testing.assert_allclose(Expression("(x >= 0.5) * 3")(x=x), [0, 0, 3, 3])
    np.testing.assert_allclose(Expression("(x == 2) + (x != 2) * 5")(x=x), [5, 5, 5, 1])
    np.testing.assert_allclose(Expression("minimum(x, 0) + maximum(x, 1)")(x=x), [-1, 0.5, 1, 2])
    np.testing.assert_allclose(Expression("abs(x)")(x=x), [2, 0.5, 0.5, 2])
    np.testing.assert_allclose(
        Expression("sqrt(exp(log(4))) + log10(100) + tanh(0) + cos(0) + tan(0)")(), 5.0
    )
    assert Expression("where(t < 10, 1, 2)")(t=5.0) == 1.0
    assert Expression("where(t < 10, 1, 2)")(t=50.0) == 2.0


def test_expression_huge_power_does_not_hang() -> None:
    assert Expression("9**9**9**9")() == float("inf")


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os')",
        "__import__('os').system('echo hi')",
        "x.real",
        "(1).__class__",
        "sin.__name__",
        "unknown + 1",
        "z",
        "np.sin(x)",
        "open('f')",
        "eval('1')",
        "'text'",
        "True",
        "None",
        "[1, 2]",
        "x[0]",
        "lambda: 1",
        "1 if x else 2",
        "x and y",
        "not x",
        "~x",
        "x // 2",
        "x << 2",
        "x @ y",
        "x is y",
        "x in y",
        "sin(x, y)",
        "where(x, 1)",
        "sin(x=1)",
        "sin(*x)",
        "(x := 1)",
        "f'{x}'",
        "1j",
        "x; y",
        "x +",
        "",
        "   ",
        "sin",
        "sin + 1",
        "pi(1)",
    ],
)
def test_expression_rejects(text: str) -> None:
    with pytest.raises(ModelError):
        Expression(text)


def test_expression_rejects_non_string_and_overlong_text() -> None:
    with pytest.raises(ModelError):
        Expression(5)  # type: ignore[arg-type]
    with pytest.raises(ModelError):
        Expression("1+" * 2000 + "1")
    with pytest.raises(ModelError):
        Expression("(" * 500 + "1" + ")" * 500)


@pytest.mark.parametrize(
    ("text", "on_T", "on_time"),
    [
        ("5", False, False),
        ("x + y", False, False),
        ("pi * e", False, False),
        ("t", False, True),
        ("T", True, False),
        ("tan(x) + tanh(y)", False, False),  # function names contain the letter t
        ("T**4 - t", True, True),
        ("where(t > 5, T, 0)", True, True),
    ],
)
def test_expression_dependency_flags(text: str, on_T: bool, on_time: bool) -> None:
    f = Expression(text)
    assert f.depends_on_T is on_T
    assert f.depends_on_time is on_time
    assert f.breakpoints() == []


# -------------------------------------------------------------------------------- JSON


def test_json_round_trip() -> None:
    functions = [
        Constant(5.0),
        Table([0.0, 1.0], [2.0, 3.0], "t"),
        Table([300.0, 400.0], [2.0, 3.0], "T", extrapolate="linear"),
        Expression("500 + 20*sin(2*pi*t/60)"),
    ]
    for f in functions:
        assert function_from_json(function_to_json(f)) == f
    assert function_to_json(Constant(5)) == {"type": "constant", "value": 5.0}
    assert function_to_json(Expression("x")) == {"type": "expression", "text": "x"}


def test_json_forms_from_the_data_model() -> None:
    assert function_from_json(5) == Constant(5.0)
    assert function_from_json(2.5) == Constant(2.5)
    assert function_from_json({"type": "constant", "value": 5}) == Constant(5.0)
    table = function_from_json({"type": "table", "variable": "t", "xs": [0, 1], "ys": [2, 3]})
    assert table == Table([0.0, 1.0], [2.0, 3.0], "t", "hold")
    assert function_from_json({"type": "expression", "text": "x+1"}) == Expression("x+1")
    for bad in ("5", True, None, {"value": 5}, {"type": "spline"}, {"type": "table", "xs": [0]}):
        with pytest.raises(ModelError):
            function_from_json(bad)
    with pytest.raises(ModelError):
        function_to_json(object())  # type: ignore[arg-type]


def test_as_function() -> None:
    assert as_function(3) == Constant(3.0)
    f = Expression("x")
    assert as_function(f) is f
    with pytest.raises(ModelError):
        as_function("x")  # type: ignore[arg-type]
    with pytest.raises(ModelError):
        as_function(True)
