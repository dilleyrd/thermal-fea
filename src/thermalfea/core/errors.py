"""Exception hierarchy for ThermalFEA (Data §12).

The GUI shows the message of any :class:`ThermalFEAError` in a dialog. Any other
exception is a bug and is logged with its traceback.
"""

from __future__ import annotations


class ThermalFEAError(Exception):
    """Base class of every error raised deliberately by ThermalFEA."""


class ModelError(ThermalFEAError):
    """Bad user input: an invalid or inconsistent model definition."""


class GeometryError(ThermalFEAError):
    """A geometry operation or import failed."""


class MeshError(ThermalFEAError):
    """Mesh generation failed or produced an unusable mesh."""


class ConvergenceError(ThermalFEAError):
    """A nonlinear or time-stepping iteration did not converge."""


class SolverError(ThermalFEAError):
    """The linear solver failed (singular matrix, non-finite values, ...)."""
