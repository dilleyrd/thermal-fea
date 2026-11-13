"""Error hierarchy (Data §12) and logging helpers."""

import logging

import pytest

from thermalfea.core import errors
from thermalfea.core.log import configure_logging, get_logger


@pytest.mark.parametrize(
    "cls",
    [
        errors.ModelError,
        errors.GeometryError,
        errors.MeshError,
        errors.ConvergenceError,
        errors.SolverError,
    ],
)
def test_all_errors_derive_from_base(cls: type[Exception]) -> None:
    assert issubclass(cls, errors.ThermalFEAError)
    with pytest.raises(errors.ThermalFEAError, match="boom"):
        raise cls("boom")


def test_logger_names() -> None:
    assert get_logger().name == "thermalfea"
    assert get_logger("thermalfea.solver.linear").name == "thermalfea.solver.linear"
    assert get_logger("other").name == "thermalfea.other"


def test_configure_logging_is_idempotent() -> None:
    logger = logging.getLogger("thermalfea")
    before, level = list(logger.handlers), logger.level
    try:
        assert configure_logging(logging.WARNING) is logger
        n = len(logger.handlers)
        assert n == len(before) + 1
        assert configure_logging(logging.WARNING) is logger
        assert len(logger.handlers) == n
        assert logger.level == logging.WARNING
    finally:  # leave the logger as it was for the other tests
        logger.handlers[:] = before
        logger.setLevel(level)
