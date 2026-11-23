# ThermalFEA

ThermalFEA is a program for two-dimensional steady-state and transient heat conduction by the
finite-element method. It has a desktop window, a Python API and a command line.
It handles planar and axisymmetric models. It includes convection correlations and a
one-dimensional stream and pipe-network flow model.

Enclosure radiation and phase change are on hold and are not available in this version.

## Install from source

Requires Python 3.11 or newer. In a terminal, in the project folder:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

Optional extras:

```
.venv\Scripts\python.exe -m pip install -e ".[dxf]"        (DXF import)
.venv\Scripts\python.exe -m pip install -e ".[examples]"   (pump-closure showcase scripts, need pandas)
```

## Start

Open the window:

```
.venv\Scripts\python.exe -m thermalfea.gui.app
```

or `.venv\Scripts\thermalfea-gui.exe`, which opens it without a console.

Solve a model from the command line:

```
.venv\Scripts\thermalfea.exe solve model.tfea
```

## Documentation

The user guide is at <https://dilleyrd.github.io/thermal-fea/>.

## Licence

MIT licence, see [LICENSE](LICENSE).
