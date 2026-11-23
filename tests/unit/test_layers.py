"""Layer rules of Plan §3, enforced by parsing every source file with ``ast``.

* Only ``geometry/`` and ``meshing/`` may import ``gmsh``.
* Only ``gui/`` may import ``PySide6`` or ``thermalfea.gui``.
* Inside ``gui/`` only the modules in :data:`MATPLOTLIB_GUI_ALLOWED` may import Matplotlib
  (Plan §7 rule 8: the model view is reached only through ``SceneView``).
* ``gui/scene.py`` (the interface) imports no Matplotlib and, of PySide6, only the
  ``QtCore`` / ``QtWidgets`` names its annotations need (``Signal``, ``QWidget``).
* Only ``solver/linear.py`` may import ``scipy.sparse.linalg``.
* No module under ``src/thermalfea`` calls the built-in ``print``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "thermalfea"

GMSH_ALLOWED = ("geometry", "meshing")
GUI_ALLOWED = ("gui",)

#: GUI modules (relative to the package, POSIX) that may import Matplotlib. Only the model
#: viewport and, as they are created, chart modules (history/path charts M8.11, the table
#: preview plot M8.4) belong here: add each chart module to this list when it is written.
MATPLOTLIB_GUI_ALLOWED = (
    "gui/viewport_mpl.py",
    "gui/property_panels/function_preview.py",
    "gui/property_panels/quality_histogram.py",
    "gui/dialogs/residual_plot.py",
    "gui/charts.py",
)
#: The interface module: no Matplotlib, and PySide6 only through these modules.
SCENE_MODULE = "gui/scene.py"
SCENE_PYSIDE_ALLOWED = ("PySide6", "PySide6.QtCore", "PySide6.QtWidgets")


def imported_modules(source: str, package: str) -> set[str]:
    """Return the absolute names of every module imported by ``source``.

    ``package`` is the dotted package containing the module, used to resolve
    relative imports. ``from a import b`` yields both ``a`` and ``a.b`` because
    ``b`` may itself be a module.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*parts, base] if base else parts)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _matches(module: str, root: str) -> bool:
    return module == root or module.startswith(root + ".")


def violations(source: str, rel: Path) -> list[str]:
    """Return the layer-rule violations of one file at ``rel`` (relative to the package)."""
    package = ".".join(["thermalfea", *rel.parts[:-1]])
    top = rel.parts[0] if len(rel.parts) > 1 else ""
    out: list[str] = []
    for mod in sorted(imported_modules(source, package)):
        if _matches(mod, "gmsh") and top not in GMSH_ALLOWED:
            out.append(f"{rel.as_posix()}: imports {mod} outside geometry/ and meshing/")
        if (_matches(mod, "PySide6") or _matches(mod, "thermalfea.gui")) and (
            top not in GUI_ALLOWED
        ):
            out.append(f"{rel.as_posix()}: imports {mod} outside gui/")
        if (
            top in GUI_ALLOWED
            and _matches(mod, "matplotlib")
            and rel.as_posix() not in MATPLOTLIB_GUI_ALLOWED
        ):
            out.append(f"{rel.as_posix()}: imports {mod}; only {MATPLOTLIB_GUI_ALLOWED} may")
        if rel.as_posix() == SCENE_MODULE and _matches(mod, "PySide6"):
            allowed = any(
                mod == a or (mod.startswith(a + ".") and a != "PySide6")
                for a in SCENE_PYSIDE_ALLOWED
            )
            if not allowed:
                out.append(f"{rel.as_posix()}: imports {mod}; only QtCore/QtWidgets names")
    return out


def test_layer_rules() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no source files found under {SRC}"
    problems: list[str] = []
    for path in files:
        problems += violations(path.read_text(encoding="utf-8"), path.relative_to(SRC))
    assert not problems, "\n".join(problems)


def test_detects_gmsh_outside_geometry() -> None:
    assert violations("import gmsh\n", Path("solver/linear.py"))
    assert violations("from gmsh import model\n", Path("core/mesh.py"))
    assert violations("import gmsh\n", Path("api.py"))
    assert not violations("import gmsh\n", Path("geometry/builder.py"))
    assert not violations("import gmsh\n", Path("meshing/mesher.py"))


def test_detects_gui_imports_outside_gui() -> None:
    assert violations("from PySide6.QtWidgets import QWidget\n", Path("post/plots.py"))
    assert violations("import PySide6\n", Path("api.py"))
    assert violations("import thermalfea.gui.app\n", Path("solver/steady.py"))
    assert violations("from thermalfea import gui\n", Path("cli.py"))
    assert violations("from ..gui import scene\n", Path("post/plots.py"))
    assert violations("from . import gui\n", Path("api.py"))
    assert not violations("from PySide6.QtWidgets import QWidget\n", Path("gui/app.py"))
    assert not violations("from . import scene\n", Path("gui/app.py"))


def test_detects_matplotlib_in_gui_outside_allow_list() -> None:
    assert violations("import matplotlib.pyplot\n", Path("gui/main_window.py"))
    assert violations("from matplotlib.collections import LineCollection\n", Path("gui/a.py"))
    assert violations("from matplotlib import cm\n", Path("gui/dialogs/x.py"))
    assert violations("import matplotlib\n", Path("gui/scene.py"))
    for allowed in MATPLOTLIB_GUI_ALLOWED:
        assert not violations("import matplotlib\n", Path(allowed))
    # outside gui/ Matplotlib stays free (post/plots.py draws with it)
    assert not violations("from matplotlib.figure import Figure\n", Path("post/plots.py"))


def test_scene_module_is_interface_only() -> None:
    assert violations("from PySide6.QtGui import QPainter\n", Path("gui/scene.py"))
    assert violations("import PySide6.QtGui\n", Path("gui/scene.py"))
    assert not violations("from PySide6.QtCore import Signal\n", Path("gui/scene.py"))
    assert not violations("from PySide6.QtWidgets import QWidget\n", Path("gui/scene.py"))
    assert not violations("from PySide6.QtGui import QPainter\n", Path("gui/other.py"))


def test_allow_list_names_existing_files() -> None:
    for name in (*MATPLOTLIB_GUI_ALLOWED, SCENE_MODULE):
        assert (SRC / name).is_file(), name


def test_allowed_imports_pass() -> None:
    assert not violations("import numpy as np\nfrom ..core import mesh\n", Path("solver/a.py"))
    assert not violations("import gmshx\nimport PySide6x\n", Path("solver/a.py"))


#: The only module that may import ``scipy.sparse.linalg`` (the sparse LU factorisation).
SPARSE_LINALG_ALLOWED = ("solver/linear.py",)


def sparse_linalg_violations(source: str, rel: Path) -> list[str]:
    """Return the violations of ``scipy.sparse.linalg`` imports in one file."""
    if rel.as_posix() in SPARSE_LINALG_ALLOWED:
        return []
    package = ".".join(["thermalfea", *rel.parts[:-1]])
    return [
        f"{rel.as_posix()}: imports {mod}; only {SPARSE_LINALG_ALLOWED} may"
        for mod in sorted(imported_modules(source, package))
        if _matches(mod, "scipy.sparse.linalg")
    ]


def print_call_violations(source: str, rel: Path) -> list[str]:
    """Return one entry per call of the built-in ``print`` in one file."""
    return [
        f"{rel.as_posix()}:{node.lineno}: calls print"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]


def test_sparse_linalg_only_in_linear_solver() -> None:
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        problems += sparse_linalg_violations(path.read_text(encoding="utf-8"), rel)
    assert not problems, "\n".join(problems)


def test_detects_sparse_linalg_outside_linear_solver() -> None:
    assert sparse_linalg_violations("import scipy.sparse.linalg\n", Path("solver/steady.py"))
    assert sparse_linalg_violations(
        "from scipy.sparse.linalg import splu\n", Path("solver/steady.py")
    )
    assert sparse_linalg_violations("from scipy.sparse import linalg\n", Path("core/x.py"))
    assert not sparse_linalg_violations(
        "from scipy.sparse.linalg import splu\n", Path("solver/linear.py")
    )
    assert not sparse_linalg_violations("from scipy.sparse import csr_matrix\n", Path("core/x.py"))


def test_no_print_calls_in_package() -> None:
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        problems += print_call_violations(path.read_text(encoding="utf-8"), rel)
    assert not problems, "\n".join(problems)


def test_detects_print_call() -> None:
    assert print_call_violations('print("x")\n', Path("solver/steady.py"))
    assert print_call_violations("def f():\n    print()\n", Path("api.py"))
    assert not print_call_violations("pprint_all(x)\nlogger.info('x')\n", Path("api.py"))
    assert not print_call_violations("# print('x')\n", Path("api.py"))
