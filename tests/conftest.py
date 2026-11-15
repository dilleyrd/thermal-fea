"""Shared test fixtures."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_package_logger() -> Iterator[None]:
    """Leave the ``thermalfea`` logger as each test found it.

    Code under test (the CLI, ``configure_logging``) attaches handlers and changes the
    level; without this they would leak into later tests.
    """
    logger = logging.getLogger("thermalfea")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate
