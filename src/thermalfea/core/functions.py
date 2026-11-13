"""Functions used for load and property values (Data §1).

Every numeric load or property field accepts a :class:`Function`: a :class:`Constant`, a
piecewise-linear :class:`Table` against time or temperature, or an :class:`Expression` of
``t``, ``x``, ``y`` and ``T``. Expressions are evaluated by walking a validated syntax
tree; the text is never passed to ``eval``.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
from numpy import ndarray

from .errors import ModelError

Value = ndarray | float


@runtime_checkable
class Function(Protocol):
    """A value that may depend on time, position and temperature.

    Calling it with time ``t`` [s], position ``x``, ``y`` [m] and temperature ``T`` [K]
    returns the value in the SI unit of the quantity it describes. Array arguments are
    broadcast against each other and the result has the broadcast shape.
    """

    depends_on_T: bool
    depends_on_time: bool

    def __call__(
        self, t: float = 0.0, x: Value = 0.0, y: Value = 0.0, T: Value = 0.0
    ) -> Value: ...

    def breakpoints(self) -> list[float]:
        """Times [s] the time stepper must land on."""
        ...


def _finish(value: Any, x: Value, y: Value, T: Value) -> Value:
    """Convert a result to float and give it the broadcast shape of the array arguments."""
    shape = np.broadcast_shapes(np.shape(value), np.shape(x), np.shape(y), np.shape(T))
    out = np.asarray(value, dtype=float)
    if shape == ():
        return float(out)
    return np.broadcast_to(out, shape).copy()


# ---------------------------------------------------------------------------- Constant


@dataclass
class Constant:
    """A fixed value.

    Parameters
    ----------
    value : float
        The value, in the SI unit of the quantity it describes.
    """

    value: float

    depends_on_T = False
    depends_on_time = False

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ModelError(f"constant value must be a number, got {self.value!r}")
        self.value = float(self.value)
        if not np.isfinite(self.value):
            raise ModelError("constant value must be finite")

    def __call__(
        self, t: float = 0.0, x: Value = 0.0, y: Value = 0.0, T: Value = 0.0
    ) -> Value:
        return _finish(self.value, x, y, T)

    def breakpoints(self) -> list[float]:
        return []


# ------------------------------------------------------------------------------- Table


@dataclass
class Table:
    """Piecewise-linear table against time or temperature.

    Parameters
    ----------
    xs : list of float
        Strictly increasing abscissae: times [s] or temperatures [K].
    ys : list of float
        Values at ``xs``, in the SI unit of the quantity described.
    variable : {"t", "T"}
        The independent variable.
    extrapolate : {"hold", "linear"}
        Outside the table: hold the end value, or continue the end segment.
    """

    xs: list[float]
    ys: list[float]
    variable: Literal["t", "T"]
    extrapolate: Literal["hold", "linear"] = "hold"
    _x: ndarray = field(init=False, repr=False, compare=False)
    _y: ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.variable not in ("t", "T"):
            raise ModelError(f"table variable must be 't' or 'T', got {self.variable!r}")
        if self.extrapolate not in ("hold", "linear"):
            raise ModelError(
                f"table extrapolation must be 'hold' or 'linear', got {self.extrapolate!r}"
            )
        try:
            self.xs = [float(v) for v in self.xs]
            self.ys = [float(v) for v in self.ys]
        except (TypeError, ValueError) as exc:
            raise ModelError(f"table entries must be numbers: {exc}") from None
        if len(self.xs) != len(self.ys):
            raise ModelError("table xs and ys have different lengths")
        if not self.xs:
            raise ModelError("table is empty")
        self._x = np.array(self.xs)
        self._y = np.array(self.ys)
        if not (np.all(np.isfinite(self._x)) and np.all(np.isfinite(self._y))):
            raise ModelError("table entries must be finite")
        if np.any(np.diff(self._x) <= 0.0):
            raise ModelError("table xs must be strictly increasing")

    @property
    def depends_on_T(self) -> bool:
        return self.variable == "T"

    @property
    def depends_on_time(self) -> bool:
        return self.variable == "t"

    def __call__(
        self, t: float = 0.0, x: Value = 0.0, y: Value = 0.0, T: Value = 0.0
    ) -> Value:
        u = np.asarray(t if self.variable == "t" else T, dtype=float)
        value = np.interp(u, self._x, self._y)  # holds the end values outside the table
        if self.extrapolate == "linear" and self._x.size > 1:
            lo = (self._y[1] - self._y[0]) / (self._x[1] - self._x[0])
            hi = (self._y[-1] - self._y[-2]) / (self._x[-1] - self._x[-2])
            value = np.where(u < self._x[0], self._y[0] + lo * (u - self._x[0]), value)
            value = np.where(u > self._x[-1], self._y[-1] + hi * (u - self._x[-1]), value)
        return _finish(value, x, y, T)

    def breakpoints(self) -> list[float]:
        return list(self.xs) if self.variable == "t" else []


# -------------------------------------------------------------------------- Expression

_NAMES = ("t", "x", "y", "T", "pi", "e")
_CONSTANTS = {"pi": np.pi, "e": np.e}

_FUNCTIONS: dict[str, tuple[Callable[..., Any], int]] = {
    "sin": (np.sin, 1),
    "cos": (np.cos, 1),
    "tan": (np.tan, 1),
    "exp": (np.exp, 1),
    "log": (np.log, 1),
    "log10": (np.log10, 1),
    "sqrt": (np.sqrt, 1),
    "abs": (np.abs, 1),
    "tanh": (np.tanh, 1),
    "minimum": (np.minimum, 2),
    "maximum": (np.maximum, 2),
    "where": (np.where, 3),
}

_BINARY: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_COMPARE: dict[type, Callable[[Any, Any], Any]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}

_MAX_TEXT_LENGTH = 2000


def _validate(node: ast.AST, names: set[str]) -> None:
    """Raise ``ModelError`` unless ``node`` uses only the allowed syntax; collect names."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ModelError(f"expression: only numbers are allowed, got {node.value!r}")
    elif isinstance(node, ast.Name):
        if node.id not in _NAMES:
            raise ModelError(
                f"expression: unknown name {node.id!r} (allowed: {', '.join(_NAMES)})"
            )
        names.add(node.id)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BINARY:
            raise ModelError(f"expression: operator {type(node.op).__name__} is not allowed")
        _validate(node.left, names)
        _validate(node.right, names)
    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            raise ModelError(f"expression: operator {type(node.op).__name__} is not allowed")
        _validate(node.operand, names)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARE:
                raise ModelError(f"expression: comparison {type(op).__name__} is not allowed")
        _validate(node.left, names)
        for comparator in node.comparators:
            _validate(comparator, names)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            called = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
            raise ModelError(
                f"expression: call to {called!r} is not allowed "
                f"(allowed: {', '.join(sorted(_FUNCTIONS))})"
            )
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise ModelError("expression: keyword and starred arguments are not allowed")
        n_args = _FUNCTIONS[node.func.id][1]
        if len(node.args) != n_args:
            raise ModelError(
                f"expression: {node.func.id} takes {n_args} argument(s), got {len(node.args)}"
            )
        for arg in node.args:
            _validate(arg, names)
    else:
        raise ModelError(f"expression: {type(node).__name__} is not allowed")


def _evaluate(node: ast.AST, env: dict[str, Any]) -> Any:
    """Evaluate a validated tree with NumPy semantics."""
    if isinstance(node, ast.Constant):
        return np.float64(node.value)
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.BinOp):
        return _BINARY[type(node.op)](_evaluate(node.left, env), _evaluate(node.right, env))
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_evaluate(node.operand, env))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, env)
        result: Any = True
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, env)
            result = np.logical_and(result, _COMPARE[type(op)](left, right))
            left = right
        return result
    if isinstance(node, ast.Call):
        func = _FUNCTIONS[node.func.id][0]  # type: ignore[attr-defined]
        return func(*(_evaluate(arg, env) for arg in node.args))
    raise ModelError(f"expression: {type(node).__name__} is not allowed")  # pragma: no cover


@dataclass
class Expression:
    """A formula in the variables ``t`` [s], ``x``, ``y`` [m] and ``T`` [K].

    Allowed: numbers, the names ``t x y T pi e``, the operators ``+ - * / ** %``,
    comparisons, and calls to ``sin cos tan exp log log10 sqrt abs minimum maximum where
    tanh``. Anything else raises :class:`~thermalfea.core.errors.ModelError`.

    Parameters
    ----------
    text : str
        The formula, e.g. ``"500 + 20*sin(2*pi*t/60)"``.
    """

    text: str
    _tree: ast.AST = field(init=False, repr=False, compare=False)
    _names: frozenset[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ModelError("expression text is empty")
        if len(self.text) > _MAX_TEXT_LENGTH:
            raise ModelError(f"expression is longer than {_MAX_TEXT_LENGTH} characters")
        try:
            tree = ast.parse(self.text.strip(), mode="eval")
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            raise ModelError(f"expression {self.text!r} is not valid: {exc}") from None
        names: set[str] = set()
        try:
            _validate(tree.body, names)
        except RecursionError:
            raise ModelError("expression is nested too deeply") from None
        self._tree = tree.body
        self._names = frozenset(names)

    @property
    def depends_on_T(self) -> bool:
        return "T" in self._names

    @property
    def depends_on_time(self) -> bool:
        return "t" in self._names

    def __call__(
        self, t: float = 0.0, x: Value = 0.0, y: Value = 0.0, T: Value = 0.0
    ) -> Value:
        env = {
            "t": np.float64(t),
            "x": np.asarray(x, dtype=float),
            "y": np.asarray(y, dtype=float),
            "T": np.asarray(T, dtype=float),
            **_CONSTANTS,
        }
        with np.errstate(all="ignore"):  # non-finite results are reported by the solver
            value = _evaluate(self._tree, env)
        return _finish(value, x, y, T)

    def breakpoints(self) -> list[float]:
        return []


# -------------------------------------------------------------------------------- JSON


def function_to_json(f: Function) -> dict[str, Any]:
    """Return the JSON form of a function (Data §1).

    Raises
    ------
    ModelError
        If ``f`` is not one of the three function classes.
    """
    if isinstance(f, Constant):
        return {"type": "constant", "value": f.value}
    if isinstance(f, Table):
        return {
            "type": "table",
            "variable": f.variable,
            "xs": list(f.xs),
            "ys": list(f.ys),
            "extrapolate": f.extrapolate,
        }
    if isinstance(f, Expression):
        return {"type": "expression", "text": f.text}
    raise ModelError(f"cannot serialise function of type {type(f).__name__}")


def function_from_json(obj: Any) -> Function:
    """Build a function from its JSON form; a bare number is read as a :class:`Constant`.

    Raises
    ------
    ModelError
        If the JSON form is not recognised.
    """
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return Constant(obj)
    if not isinstance(obj, dict) or "type" not in obj:
        raise ModelError(f"not a function definition: {obj!r}")
    kind = obj["type"]
    try:
        if kind == "constant":
            return Constant(obj["value"])
        if kind == "table":
            return Table(
                obj["xs"], obj["ys"], obj["variable"], obj.get("extrapolate", "hold")
            )
        if kind == "expression":
            return Expression(obj["text"])
    except KeyError as exc:
        raise ModelError(f"function definition of type {kind!r} lacks {exc}") from None
    raise ModelError(f"unknown function type {kind!r}")


def as_function(value: Function | float) -> Function:
    """Return ``value`` as a function, wrapping a bare number in a :class:`Constant`."""
    if isinstance(value, (Constant, Table, Expression)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Constant(value)
    if isinstance(value, Function):
        return value
    raise ModelError(f"expected a function or a number, got {value!r}")
