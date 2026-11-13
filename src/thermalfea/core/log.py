"""Logging helpers. All modules log through ``logging``; nothing prints."""

from __future__ import annotations

import logging

ROOT_LOGGER_NAME = "thermalfea"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_HANDLER_NAME = "thermalfea-default"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the package logger or one of its children.

    Parameters
    ----------
    name : str, optional
        Module name, normally ``__name__``. Names outside the ``thermalfea``
        namespace are placed under it.

    Returns
    -------
    logging.Logger
    """
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def configure_logging(level: int | str = logging.INFO) -> logging.Logger:
    """Attach a stream handler to the package logger (idempotent).

    Parameters
    ----------
    level : int or str
        Logging level for the package logger.

    Returns
    -------
    logging.Logger
        The configured package logger.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(level)
    if not any(h.get_name() == _HANDLER_NAME for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    return logger
