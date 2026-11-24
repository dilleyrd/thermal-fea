# PyInstaller spec of the Windows build (task M11.5).
#
#   .venv\Scripts\python.exe -m PyInstaller packaging\thermalfea.spec --noconfirm ^
#       --distpath dist --workpath build
#
# One onedir folder, dist/ThermalFEA/, shared by two programs built from one analysis:
#   ThermalFEA.exe  the GUI (windowed, no console)
#   thermalfea-cli.exe  the command line (a different name: Windows file names ignore case) (console)
# The gmsh Python module looks for its library next to itself; in a frozen program that is
# the folder of the modules (_internal), so the DLL is put at the top of that folder.
import os

import gmsh
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

here = os.path.dirname(os.path.abspath(SPEC))  # packaging/

hiddenimports = collect_submodules("thermalfea") + collect_submodules("meshio") + [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
]
datas = collect_data_files("thermalfea")  # materials/data/*.json, gui/examples/*
try:  # DXF import is optional: ship it when the build environment has it
    import ezdxf  # noqa: F401

    hiddenimports += collect_submodules("ezdxf")
    datas += collect_data_files("ezdxf")
except ImportError:
    pass
binaries = [(gmsh.libpath, ".")]  # gmsh-4.15.dll, found by gmsh.py beside itself

# not imported by the program at run time (pandas is only for the example scripts)
excludes = ["pandas", "tkinter", "pytest", "pytest_qt", "IPython", "ruff", "mkdocs",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
            "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"]

a = Analysis(
    [os.path.join(here, "gui_entry.py"), os.path.join(here, "cli_entry.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)


def entry_scripts(name):
    """The bootstrap scripts plus the one entry script ``name`` (entry scripts come last)."""
    entries = ("gui_entry", "cli_entry")
    return [s for s in a.scripts if s[0] not in entries] + [s for s in a.scripts if s[0] == name]


gui = EXE(
    pyz, entry_scripts("gui_entry"),
    exclude_binaries=True, name="ThermalFEA", console=False, upx=False, debug=False,
)
cli = EXE(
    pyz, entry_scripts("cli_entry"),
    exclude_binaries=True, name="thermalfea-cli", console=True, upx=False, debug=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, upx=False, name="ThermalFEA")
