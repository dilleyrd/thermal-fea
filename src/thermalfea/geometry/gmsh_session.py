"""The single gateway to gmsh (Plan §3 layer rule 2).

gmsh keeps global state and is not thread-safe, so the whole process shares one
:class:`GmshSession`, guarded by a re-entrant lock. It is initialised without signal
handlers so it can run in a worker thread, prints nothing to the terminal, and forwards
gmsh's messages to :mod:`logging`.

Usage::

    with GmshSession.get().fresh_model("part") as gmsh:
        gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
        gmsh.model.occ.synchronize()

The model stays alive after the block (the mesher works on it) until the next
``fresh_model`` clears it. Later work on the same model uses ``session.use(name)``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType

import gmsh

from ..core.errors import GeometryError

log = logging.getLogger(__name__)

_LEVELS = {"Error": logging.ERROR, "Warning": logging.WARNING}


class GmshSession:
    """Process-wide owner of the gmsh library state. Obtain it with :meth:`get`."""

    _instance: GmshSession | None = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._initialized = False
        self._model_name: str | None = None
        self._serial = 0

    @classmethod
    def get(cls) -> GmshSession:
        """Return the singleton session, creating it on first use."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------ life cycle

    def _ensure_initialized(self) -> None:
        if self._initialized and gmsh.isInitialized():
            return
        if not gmsh.isInitialized():
            # interruptible=False: install no signal handlers, so this also works when
            # first called from a worker thread.
            gmsh.initialize(readConfigFiles=False, interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 5)  # up to "Info"; all go to logging
        gmsh.logger.start()
        self._initialized = True
        log.debug("gmsh %s initialised", gmsh.__version__)

    def finalize(self) -> None:
        """Shut gmsh down. The next use initialises it again."""
        with self.lock:
            if gmsh.isInitialized():
                self.flush_messages()
                gmsh.logger.stop()
                gmsh.finalize()
            self._initialized = False
            self._model_name = None

    # -------------------------------------------------------------------- messages

    def flush_messages(self) -> list[str]:
        """Forward the messages gmsh produced since the last call to ``logging``.

        Returns
        -------
        list of str
            The messages, each prefixed by its gmsh level (``"Info: ..."``).
        """
        with self.lock:
            if not (self._initialized and gmsh.isInitialized()):
                return []
            messages = list(gmsh.logger.get())
            gmsh.logger.stop()
            gmsh.logger.start()
        for message in messages:
            level, _, text = message.partition(": ")
            log.log(_LEVELS.get(level, logging.DEBUG), "gmsh: %s", text or message)
        return messages

    # ---------------------------------------------------------------------- models

    @property
    def model_name(self) -> str | None:
        """Name of the model currently held by gmsh, or ``None``."""
        return self._model_name

    @property
    def serial(self) -> int:
        """Counter incremented by every :meth:`fresh_model`; identifies a build."""
        return self._serial

    @contextmanager
    def fresh_model(self, name: str) -> Iterator[ModuleType]:
        """Clear the previous model, start a new one and hold the lock for the block.

        Parameters
        ----------
        name : str
            Name of the new gmsh model.

        Yields
        ------
        module
            The ``gmsh`` module, ready for use.
        """
        with self.lock:
            self._ensure_initialized()
            gmsh.clear()
            gmsh.model.add(name)
            self._model_name = name
            self._serial += 1
            try:
                yield gmsh
            finally:
                self.flush_messages()

    @contextmanager
    def use(self, serial: int | None = None) -> Iterator[ModuleType]:
        """Hold the lock to continue working on the current model.

        Parameters
        ----------
        serial : int, optional
            The :attr:`serial` of the build the caller expects to find.

        Raises
        ------
        GeometryError
            If there is no current model, or it is not the expected build.
        """
        with self.lock:
            if not (self._initialized and gmsh.isInitialized()) or self._model_name is None:
                raise GeometryError("there is no built geometry in the gmsh session")
            if serial is not None and serial != self._serial:
                raise GeometryError(
                    "the geometry in the gmsh session has been rebuilt since this "
                    "BuiltGeometry was made; build the model again"
                )
            try:
                yield gmsh
            finally:
                self.flush_messages()


def fresh_model(name: str):
    """Shortcut for ``GmshSession.get().fresh_model(name)``."""
    return GmshSession.get().fresh_model(name)
