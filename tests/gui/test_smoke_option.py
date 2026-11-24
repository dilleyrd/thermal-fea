"""The ``--smoke-test`` option of the GUI (the hook that checks a frozen build).

Run in-process and offscreen; the frozen executable itself is tested by
``tests/packaging/test_frozen.py``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import make_settings
from thermalfea.gui import app as app_module
from thermalfea.gui.app import build_application, create_app
from thermalfea.gui.file_tools import EXAMPLES_DIR
from thermalfea.gui.smoke import run_smoke_test, write_status

EXAMPLE = "v01_slab.tfea"


@pytest.fixture
def model(tmp_path: Path) -> Path:
    """A copy of a shipped example, so the results file lands in ``tmp_path``."""
    target = tmp_path / EXAMPLE
    shutil.copy(EXAMPLES_DIR / EXAMPLE, target)
    return target


def test_run_smoke_test_solves_a_model(qtbot, tmp_path: Path, model: Path) -> None:
    app = create_app()
    ctx = build_application(make_settings(tmp_path / "s.ini"), install_hook=False)
    qtbot.addWidget(ctx.window)
    try:
        status = run_smoke_test(app, ctx, model)
    finally:
        assert ctx.shutdown(5000)
    assert status["ok"], status
    assert status["stage"] == "done" and status["error"] == ""
    assert status["outcome"] == "finished"
    assert status["nodes"] > 0 and status["elements"] > 0
    assert status["t_max"] > status["t_min"] > 0.0  # kelvin
    assert Path(status["results"]).is_file()


def test_run_smoke_test_reports_a_bad_file(qtbot, tmp_path: Path) -> None:
    app = create_app()
    ctx = build_application(make_settings(tmp_path / "s.ini"), install_hook=False)
    qtbot.addWidget(ctx.window)
    try:
        status = run_smoke_test(app, ctx, tmp_path / "missing.tfea")
    finally:
        assert ctx.shutdown(5000)
    assert not status["ok"] and status["stage"] == "open" and status["error"]


def test_main_option_writes_status_and_returns_zero(
    qtbot, tmp_path: Path, model: Path, monkeypatch
) -> None:
    ini = tmp_path / "default.ini"  # keep the user's real settings untouched
    monkeypatch.setattr(app_module, "build_application",
                        lambda: build_application(make_settings(ini)))
    out = tmp_path / "status.json"
    code = app_module.main(
        ["thermalfea-gui", "--smoke-test", str(model), "--smoke-out", str(out)]
    )
    assert code == 0
    status = json.loads(out.read_text(encoding="utf-8"))
    assert status["ok"] and status["outcome"] == "finished"


def test_main_option_returns_one_on_failure(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    ini = tmp_path / "default.ini"
    monkeypatch.setattr(app_module, "build_application",
                        lambda: build_application(make_settings(ini)))
    out = tmp_path / "status.json"
    code = app_module.main(
        ["thermalfea-gui", "--smoke-test", str(tmp_path / "nope.tfea"), "--smoke-out", str(out)]
    )
    assert code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False


def test_write_status_to_stdout(capsys) -> None:
    write_status({"ok": True}, None)
    assert json.loads(capsys.readouterr().out) == {"ok": True}
