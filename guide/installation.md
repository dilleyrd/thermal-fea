# Installation

ThermalFEA is installed from its source folder into a Python virtual environment. A
packaged Windows installer does not exist yet; it is planned (task M11.5).

## Requirements

- Python 3.11 or newer (the project is developed with Python 3.13).
- The packages the program depends on are installed automatically: NumPy, SciPy, gmsh,
  PySide6, Matplotlib, h5py and meshio.

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
  surfaces, curves and points, the materials, regions and loads, the mesh size and a short
  quality line.
- `thermalfea solve model.tfea` builds, meshes and solves the model. It prints one
  progress line per step and then a text summary. The results go to `model.tfea.h5` beside
  the model.
- `-o RESULTS`, `--output RESULTS` writes the results to the file you name instead.
- `--restart` continues the transient run stored in the results file, from its last
  stored step to the end time of the model, and adds the new steps to the same file. See
  [Getting started](getting-started.md#continuing-a-transient-run).
- `-v`, `--verbose` (given before the command name) shows the log messages.

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
