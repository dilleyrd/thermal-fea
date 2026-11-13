"""Layer rules of Plan §3, enforced by parsing every source file with ``ast``.

* Only ``geometry/`` and ``meshing/`` may import ``gmsh``.
* Only ``gui/`` may import ``PySide6`` or ``thermalfea.gui``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "thermalfea"

GMSH_ALLOWED = ("geometry", "meshing")
GUI_ALLOWED = ("gui",)


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


def test_allowed_imports_pass() -> None:
    assert not violations("import numpy as np\nfrom ..core import mesh\n", Path("solver/a.py"))
    assert not violations("import gmshx\nimport PySide6x\n", Path("solver/a.py"))
