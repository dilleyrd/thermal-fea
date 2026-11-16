"""Form specifications of the solution settings and the initial condition (Plan M8.9). No Qt.

They are registered with :func:`thermalfea.core.forms.register_form` when
:mod:`thermalfea.model.model` is imported. Every :class:`SolutionSettings` field is listed;
the limits mirror ``SolutionSettings.__post_init__`` (at least one output step and one
iteration). ``theta`` (0 < theta <= 1) has no field limit on purpose: the model's own check
refuses a bad value and its message ("theta must be in (0, 1]") is shown by the panel.

:data:`TRANSIENT_ONLY_FIELDS` and :data:`OUTPUT_EVERY_FIELD` / :data:`OUTPUT_TIMES_FIELD`
tell the panel which fields matter for which analysis kind; the ``kind`` itself and the
nonlinear controls (``rtol``, ``ttol``, ``max_iterations``, ``line_search``) always apply.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from .model import InitialCondition
from .settings import SolutionSettings

#: Fields that only a transient analysis uses.
TRANSIENT_ONLY_FIELDS: tuple[str, ...] = (
    "end_time", "initial_dt", "dt_min", "dt_max", "auto_timestep", "time_tol",
    "max_dT_per_step", "theta", "lumped_capacitance", "output", "output_every",
    "output_times",
)  # fmt: skip
#: Output field used only when ``output == "every_n"``.
OUTPUT_EVERY_FIELD = "output_every"
#: Output field used only when ``output == "times"``.
OUTPUT_TIMES_FIELD = "output_times"

SOLUTION_FORM = FormSpec(
    "Analysis settings",
    [
        FieldSpec(
            "kind", "Analysis type", "choice", choices=("steady", "transient"),
            tooltip="Steady state, or transient (time stepping).",
        ),  # fmt: skip
        FieldSpec(
            "end_time", "End time", "float", quantity="time", minimum=0.0,
            tooltip="Time at which a transient analysis ends.",
        ),  # fmt: skip
        FieldSpec(
            "initial_dt", "Initial time step", "float", quantity="time", minimum=0.0,
            optional=True, tooltip="First time step; empty uses the suggested value.",
        ),  # fmt: skip
        FieldSpec(
            "dt_min", "Smallest time step", "float", quantity="time", minimum=0.0,
            tooltip="The step is never reduced below this value.",
        ),  # fmt: skip
        FieldSpec(
            "dt_max", "Largest time step", "float", quantity="time", minimum=0.0,
            optional=True, tooltip="Upper limit of the time step; empty for none.",
        ),  # fmt: skip
        FieldSpec(
            "auto_timestep", "Adaptive time step", "bool",
            tooltip="Adapt the time step to the error estimate.",
        ),  # fmt: skip
        FieldSpec(
            "time_tol", "Time-step tolerance", "float", minimum=0.0,
            tooltip="Relative tolerance of the time-stepping error estimate.",
        ),  # fmt: skip
        FieldSpec(
            "max_dT_per_step", "Largest temperature change per step", "float",
            quantity="temperature_difference", minimum=0.0, optional=True,
            tooltip="Limit of the temperature change in one step; empty for none.",
        ),  # fmt: skip
        FieldSpec(
            "theta", "Theta", "float",
            tooltip="Time integration: 1 backward Euler, 0.5 Crank-Nicolson (0 < theta <= 1).",
        ),  # fmt: skip
        FieldSpec(
            "lumped_capacitance", "Lumped capacitance", "bool",
            tooltip="Use the lumped (diagonal) capacitance matrix.",
        ),  # fmt: skip
        FieldSpec(
            "output", "Output steps", "choice", choices=("all", "every_n", "times"),
            tooltip="Which steps are stored: all, every n-th, or at given times.",
        ),  # fmt: skip
        FieldSpec(
            OUTPUT_EVERY_FIELD, "Store every n-th step", "int", minimum=1.0,
            tooltip="Used when the output is 'every_n'.",
        ),  # fmt: skip
        FieldSpec(
            OUTPUT_TIMES_FIELD, "Output times [s]", "float_list",
            tooltip="Used when the output is 'times': comma-separated times in seconds.",
        ),  # fmt: skip
        FieldSpec(
            "rtol", "Residual tolerance", "float", minimum=0.0,
            tooltip="Relative residual tolerance of the nonlinear iteration.",
        ),  # fmt: skip
        FieldSpec(
            "ttol", "Temperature tolerance", "float", minimum=0.0,
            tooltip="Temperature-increment tolerance of the nonlinear iteration.",
        ),  # fmt: skip
        FieldSpec(
            "max_iterations", "Maximum iterations", "int", minimum=1.0,
            tooltip="Largest number of nonlinear iterations per step.",
        ),  # fmt: skip
        FieldSpec(
            "line_search", "Line search", "bool",
            tooltip="Use a line search in the nonlinear iteration.",
        ),  # fmt: skip
    ],
    category="settings",
    description="Steady or transient analysis, time stepping, output and nonlinear controls.",
)

INITIAL_CONDITION_FORM = FormSpec(
    "Initial condition",
    [
        FieldSpec(
            "kind", "Kind", "choice",
            choices=("uniform", "expression", "per_region", "from_results"),
            tooltip="Uniform, a function of x and y, one value per region, or the last "
            "step of a results file.",
        ),  # fmt: skip
        FieldSpec(
            "value", "Temperature", "function", quantity="temperature", optional=True,
            tooltip="Initial temperature for 'uniform' and 'expression'.",
        ),  # fmt: skip
        FieldSpec(
            "per_region", "Temperature per region [K]", "dict",
            tooltip="Region selection and temperature in kelvin, as 'name=T, name=T'.",
        ),  # fmt: skip
        FieldSpec(
            "results_path", "Results file", "str", optional=True,
            tooltip="Results file whose last step is the initial field.",
        ),  # fmt: skip
    ],
    category="settings",
    description="Starting temperature field of a transient analysis.",
)

register_form(SolutionSettings, SOLUTION_FORM)
register_form(InitialCondition, INITIAL_CONDITION_FORM)
