"""M11.2 — the V&V report script (``scripts/vv_report.py``): rows, scope table, literals, writer."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests" / "verification"
SCRIPT = ROOT / "scripts" / "vv_report.py"


@pytest.fixture(scope="module")
def vv():
    spec = importlib.util.spec_from_file_location("vv_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vv_report"] = module
    spec.loader.exec_module(module)
    return module


def _case(vv, case_id: str):
    return next(c for c in vv.CASES if c.id == case_id)


def test_rows_of_v01_for_one_element_type(vv) -> None:
    case = _case(vv, "V-01")
    mod = vv.cases.load("v01_slab")
    run = vv.Run("T3")
    rows = case.rows(mod, run, vv._call(mod, run))
    assert [r.quantity for r in rows][0].startswith("T, max relative error")
    assert len(rows) == 3
    for row in rows:
        assert row.case == "V-01" and row.element == "T3"
        assert row.tol == mod.TOL
        assert row.kind == "relative" and row.passed
        assert row.analytic and row.error < row.tol


def test_v17_rows_and_balance_row(vv) -> None:
    case = _case(vv, "V-17")
    mod = vv.cases.load("v17_slab_convection")
    run = vv.Run("Q4")
    result = vv._call(mod, run)
    rows = case.rows(mod, run, result) + [vv._balance_row(case, run, result)]
    assert rows[0].tol == mod.TOL and rows[0].passed
    assert rows[-1].tol == vv.cases.BALANCE_LINEAR_STEADY and rows[-1].passed
    assert rows[-1].quantity.endswith("(V-34)")


def test_v26_has_scalar_analytic_and_computed_values(vv) -> None:
    (case,) = [_case(vv, "V-26")]
    rows = vv.run_case(case)
    assert len(rows) == 2 and all(r.passed for r in rows)
    mod = vv.cases.load("v26_friction")
    assert rows[0].tol == mod.TOL_LAMINAR and rows[1].tol == mod.TOL_TURBULENT
    assert rows[0].analytic == pytest.approx(64.0 / 500.0)
    assert isinstance(rows[0].computed, float)


def test_every_version_1_case_is_in_the_table(vv) -> None:
    text = (ROOT / "docs" / "verification.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"^\| (V-\d+[a-d]?) \|", text, flags=re.MULTILINE))
    assert {"V-01", "V-37", "V-22a", "V-36"} <= ids
    table = {c.id for c in vv.CASES}
    # V-34 is the balance row of every case, not a case of its own
    expected = ids - set(vv.EXCLUDED) - {"V-34"}
    assert table == expected
    assert set(vv.EXCLUDED) == {"V-22a", "V-22b", "V-22c", "V-22d", "V-23", "V-24", "V-36"}
    assert set(vv.EXCLUDED) <= ids
    assert not set(vv.EXCLUDED) & table


def test_every_case_has_a_group_and_a_module_or_special_runner(vv) -> None:
    for case in vv.CASES:
        assert case.group
        assert case.module or case.id in vv.SPECIAL_MODULES, case.id
        if case.module:
            assert (ROOT / "examples" / f"{case.module}.py").is_file(), case.id


def test_literal_tolerances_are_in_the_cited_tests(vv) -> None:
    assert vv.LITERALS
    for name, (filename, needle, value) in vv.LITERALS.items():
        text = (TESTS / filename).read_text(encoding="utf-8")
        assert needle in text, f"{name}: {needle!r} not found in {filename}"
        # the number inside the needle is the tolerance of the table
        found = [float(n) for n in re.findall(r"\d+(?:\.\d+)?(?:e-?\d+)?", needle)]
        assert found and found[-1] == value, f"{name}: {found} != {value}"


def test_writer_escapes_pipes_and_formats_numbers(vv) -> None:
    assert vv.esc("a|b\nc") == "a\\|b c"
    assert vv.fmt(1234567.891) == "1.23457e+06"
    assert vv.fmt(0.1 + 0.2) == "0.3"
    assert vv.fmt(None) == "—"
    assert vv.fmt("linear T(x)") == "linear T(x)"
    row = vv.Row("V-99", "T3", "a | b", "x|y", 1.0 / 3.0, 1e-12, "relative", 1e-10)
    line = vv.row_line(row)
    assert "a \\| b" in line and "x\\|y" in line and "0.333333" in line
    assert line.endswith("| Pass |") and "1e-12 (relative)" in line and "< 1e-10" in line
    failing = vv.Row("V-99", "T3", "q", "1", None, 1e-9, "relative", 1e-10)
    assert not failing.passed and failing.error >= failing.tol
    assert vv.row_line(failing).endswith("| Fail |")
    order = vv.Row("V-32", "T3", "order", ">= 1.9", 2.0, 2.0, "order", 1.9, op=">=")
    assert order.passed and "≥ 1.9" in vv.row_line(order)


def test_render_has_header_summary_scope_and_no_paths(vv) -> None:
    import datetime

    case = _case(vv, "V-26")
    results = [(case, vv.run_case(case))]
    text = vv.render(results, "abc1234", True, datetime.date(2026, 1, 2))
    assert text.startswith("# Verification and validation report")
    assert "Date: 2026-01-02" in text and "Commit: abc1234 (uncommitted changes)" in text
    assert "2 rows, all passed." in text
    assert "V-22a-d, V-23, V-24 and V-36" in text
    assert "| Case | Element | Quantity | Analytic | Computed | Error | Tolerance |" in text
    assert "## Excluded from version 1" in text and "- V-36:" in text
    assert str(ROOT) not in text and "\\Users\\" not in text
    clean = vv.render(results, "abc1234", False, datetime.date(2026, 1, 2))
    assert "(uncommitted changes)" not in clean


def test_command_line_writes_the_file_and_signals_failure(vv, tmp_path: Path) -> None:
    out = tmp_path / "r.md"
    assert vv.main(["--out", str(out), "--cases", "V-26,V-31"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "V-26" in text and "V-31" in text and "V-01" not in text
    assert vv.main(["--out", str(out), "--cases", "V-99"]) == 2
