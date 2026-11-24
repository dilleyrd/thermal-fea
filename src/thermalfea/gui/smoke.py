"""Command-line smoke test of the GUI: open a model, mesh it, solve it, report, quit.

``thermalfea-gui --smoke-test MODEL --smoke-out STATUS.json`` is a hook for checking a
built (frozen) program; it is not scripting. It drives the window's own controllers
(File > Open, Mesh > Generate mesh, Solve > Solve) and writes one line of JSON to the
``--smoke-out`` file (to standard output if there is no such option). The exit code is 0 only
if the model was opened, meshed and solved.

The results go beside the model (``MODEL.h5``), as when a user solves a saved model.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEventLoop, QThread

from thermalfea.gui.app import AppContext
from thermalfea.post.results import Results

TIMEOUT_S = 120.0  # bound of each stage


def _wait(app: Any, condition: Callable[[], bool], timeout_s: float) -> bool:
    """Run the Qt event loop until ``condition()`` holds; ``False`` on timeout."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            return False
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        QThread.msleep(10)
    return True


def run_smoke_test(app: Any, context: AppContext, model: str | Path) -> dict[str, Any]:
    """Open ``model``, mesh and solve it through the window's controllers.

    Parameters
    ----------
    app : QApplication
    context : AppContext
        The wired application; its window should already be shown.
    model : str or Path
        A ``.tfea`` model file.

    Returns
    -------
    dict
        ``ok`` (bool), ``stage`` (the last stage reached), ``error`` (text, empty on
        success) and, on success, ``nodes``, ``elements``, ``outcome``, ``results``,
        ``t_min`` and ``t_max`` (temperature range of the last step).
    """
    status: dict[str, Any] = {"ok": False, "stage": "open", "error": ""}
    shown: list[str] = []
    context.window.error_dialog = lambda title, message: shown.append(f"{title}: {message}")
    context.solve.show_progress = False
    document = context.document

    def fail(text: str) -> dict[str, Any]:
        status["error"] = "; ".join([text, *shown]) if shown else text
        return status

    if not context.files.open(model):
        return fail(f"cannot open {model}")
    status["stage"] = "build"
    if not _wait(app, lambda: document.built is not None and not document.geometry_stale
                 or bool(shown), TIMEOUT_S) or shown:
        return fail("the geometry was not built")
    status["stage"] = "mesh"
    meshed: list[bool] = []
    context.mesh.meshed.connect(meshed.append)
    if not context.mesh.generate():
        return fail("meshing did not start")
    if not _wait(app, lambda: bool(meshed), TIMEOUT_S) or not meshed[0] or document.mesh is None:
        return fail("the mesh was not made")
    status.update(nodes=document.mesh.n_nodes, elements=document.mesh.n_elements)
    status["stage"] = "solve"
    if not context.solve.solve():
        return fail("the solve did not start")
    if not _wait(app, lambda: not context.solve.running, TIMEOUT_S):
        return fail("the solve did not finish")
    status["outcome"] = context.solve.outcome
    if context.solve.outcome != "finished" or document.results_path is None:
        return fail(f"the solve ended as {context.solve.outcome!r}: {context.solve.message}")
    results = Results(document.results_path)
    temperature = results.temperature()
    status.update(
        results=str(document.results_path),
        t_min=float(temperature.min()),
        t_max=float(temperature.max()),
    )
    status.update(ok=True, stage="done")
    return status


def write_status(status: dict[str, Any], out: str | Path | None) -> None:
    """Write the status as one line of JSON to ``out`` or, without it, to standard output."""
    line = json.dumps(status)
    if out is None:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    else:
        Path(out).write_text(line + "\n", encoding="utf-8")
