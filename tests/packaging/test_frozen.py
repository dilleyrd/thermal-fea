"""The built Windows program opens, solves an example and exits (task M11.5).

Runs ``scripts/smoke_exe.py`` against ``dist/ThermalFEA`` and is skipped when that folder
has not been built (``scripts/build_exe.ps1``), so the normal suite stays fast.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist" / "ThermalFEA"

pytestmark = pytest.mark.skipif(
    not (DIST / "ThermalFEA.exe").is_file(),
    reason="the Windows build dist/ThermalFEA/ThermalFEA.exe does not exist; "
    "build it with scripts/build_exe.ps1",
)


def test_built_program_smoke() -> None:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke_exe.py"), "--dist", str(DIST)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "smoke test passed" in done.stdout


def test_gmsh_library_and_qt_platform_plugin_are_bundled() -> None:
    assert list(DIST.rglob("gmsh-*.dll"))
    assert list(DIST.rglob("qwindows.dll"))
