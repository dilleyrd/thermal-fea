# Installation

ThermalFEA is installed from its source folder into a Python virtual environment. A
packaged Windows installer does not exist yet; it is planned (task M11.5).

## Requirements

- Python 3.11 or newer (the project is developed with Python 3.13).
- The packages the program depends on are installed automatically: NumPy, SciPy, gmsh,
  PySide6, Matplotlib, h5py, meshio and Pillow. pandas is installed only with the
  `examples` extra.

## Get the source

The source is on GitHub at <https://github.com/dilleyrd/thermal-fea>. Clone it with Git:

```
git clone https://github.com/dilleyrd/thermal-fea.git
cd thermal-fea
```

or download it as a zip file from that page (Code > Download ZIP) and unpack it.

## Install

From the project folder (the one with `pyproject.toml`), create a virtual environment and
install the package in it. On Windows, in a terminal:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

Use the virtual environment's Python for everything below. Do not install into the
system Python.

### Optional extras

| Extra | Installs | Needed for |
|---|---|---|
| `dxf` | `ezdxf` | importing DXF files. Without it a DXF import stops with a message that says how to install it. |
| `examples` | `pandas` | running the pump-closure showcase scripts in `examples/pump_closure/showcase/` |
| `dev` | `pytest`, `pytest-qt`, `ruff` | running the tests and the style check |
| `docs` | `mkdocs` | building this guide |

Install an extra by naming it in brackets:

```
.venv\Scripts\python.exe -m pip install -e ".[dxf]"
.venv\Scripts\python.exe -m pip install -e ".[dev,docs]"
```

## Start the program

```
.venv\Scripts\python.exe -m thermalfea.gui.app
```

An installation made since 2026-11-23 also has the command `.venv\Scripts\thermalfea-gui.exe`,
which opens the same window without a console. (An older installation gets it after
`pip install -e .` is run again.)

The main window has a model tree ("Model", top left), a property panel ("Properties",
below it), the viewport in the middle and a "Messages" dock at the bottom. The next page,
[Getting started](getting-started.md), walks through them.

## The command line

The installation adds a `thermalfea` command to the virtual environment (run it as
`.venv\Scripts\thermalfea.exe`, or `.venv\Scripts\python.exe -m thermalfea.cli`).

```
thermalfea info model.tfea
thermalfea solve model.tfea
thermalfea solve model.tfea -o results.h5
thermalfea solve model.tfea --restart
```

- `thermalfea info model.tfea` builds and meshes the model and prints the number of
  surfaces, curves and points, the materials, regions and loads, the streams, contacts
  and enclosures, the mesh size and a short quality line.
- `thermalfea solve model.tfea` builds, meshes and solves the model. It prints one
  progress line per step and then a text summary, with a table of the streams when the
  model has any. The results go to `model.tfea.h5` beside the model.
- `-o RESULTS`, `--output RESULTS` writes the results to the file you name instead.
- `--restart` continues the transient run stored in the results file, from its last
  stored step to the end time of the model, and adds the new steps to the same file. See
  [Getting started](getting-started.md#continuing-a-transient-run).
- `-v`, `--verbose` (given before the command name) also shows the informational log
  messages. Warnings (for example a correlation used outside its validity range) are
  always shown.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | a ThermalFEA error: a bad model, a geometry or mesh failure, a model that fails validation |
| 2 | the solution did not converge |

Called with no command, `thermalfea` prints its usage and exits with 0.

## Run the tests

The check script runs the style check and then the whole test suite, and stops at the first
failure:

```
.\scripts\check.ps1
```

## Build this guide

The reference pages of the guide are generated from the project's documents and code.
From the project folder:

```
.venv\Scripts\python.exe scripts\build_guide.py
.venv\Scripts\python.exe -m mkdocs build --strict
```

The first command rewrites the generated pages in `guide/` (with `--check` it only reports
whether they are out of date). The second builds the site into `site/`.

## Windows build

The program can be built into a folder that runs on Windows without Python. From the
project folder, with the virtual environment set up as above and PyInstaller installed in
it (`.venv\Scripts\python.exe -m pip install pyinstaller`):

```
powershell -NoProfile -File scriptsuild_exe.ps1
```

The script builds with the spec file `packaging\thermalfea.spec` into `dist\ThermalFEA\`
(the intermediate files go to `build\`), then runs a smoke test and exits with a non-zero
code if the build or the test fails. The build takes about a minute and the folder is
about 380 MB.

The folder holds two programs that share the files in `_internal`:

- `ThermalFEA.exe` opens the window (no console).
- `thermalfea-cli.exe` is the [command line](#the-command-line) (`thermalfea-cli.exe solve
  model.tfea`). Its name differs from the window's only because Windows file names ignore
  case.

Copy the whole `dist\ThermalFEA` folder to another computer to use it there; the programs
need no Python and no installation. The folder also holds gmsh's library, the Qt files
and the example models.

The smoke test, `scripts\smoke_exe.py`, solves the V-01 slab example with
`thermalfea-cli.exe`, then starts `ThermalFEA.exe --smoke-test MODEL --smoke-out
STATUS.json`, which opens the window (offscreen), loads the model, meshes and solves it,
writes the result to the status file and exits by itself. Run it alone with
`.venv\Scripts\python.exe scripts\smoke_exe.py`. The test suite runs it too when
`dist\ThermalFEA` exists.
