"""Background tasks for long operations (Plan M8.9): solve, and optionally build and mesh.

Thread model
------------
A :class:`BackgroundTask` is the GUI-side handle of one job. The job itself is a plain
function ``fn(context)`` run by a private :class:`QObject` (the *runner*) that is moved to
a :class:`QThread`; either a thread of its own (one per task, finished when the task ends)
or the long-lived thread of a :class:`SerialWorker` (jobs run one after the other, in the
order they were started). The runner and the task function

* never touch a widget or the :class:`~thermalfea.gui.document.Document`;
* talk to the GUI only through signals, which are connected with an explicit
  ``QueuedConnection`` to slots of the task handle, so the handle's own signals are always
  emitted in the GUI thread, whatever the thread that produced the event;
* receive a :class:`TaskContext`: ``context.report(info)`` publishes progress and returns
  ``False`` once cancellation was requested, so a solve passes
  ``lambda info: context.report(info)`` as its progress callback.

Signals of :class:`BackgroundTask` (all emitted in the GUI thread)
-----------------------------------------------------------------
``started()``
    The task was handed to its thread.
``progress(object)``
    Whatever the task passed to ``context.report``.
``finished(object)``
    The task returned its value without a cancellation request.
``failed(object)``
    The task raised; the payload is the exception. A
    :class:`~thermalfea.core.errors.ThermalFEAError` is a normal user-facing failure and is
    logged as one line; any other exception is a bug and is logged with its traceback.
``cancelled(object)``
    Cancellation was requested and the task ended (it returned a value, which is the
    payload, or raised :class:`TaskCancelled`, payload ``None``).

Exactly one of ``finished``, ``failed`` and ``cancelled`` is emitted per task. For a task
with its own thread it is emitted only after the thread has ended (``isRunning()`` is
``False``).

Cancellation
------------
:meth:`BackgroundTask.cancel` sets a :class:`threading.Event`; the task polls it through
``context.cancelled`` or ``context.report``. Nothing is ever killed. A task that ignores
the flag simply runs to its end.

Shutdown
--------
:meth:`BackgroundTask.shutdown` cancels and waits for a bounded time; :class:`SerialWorker`
``shutdown`` does the same for its thread. A thread that does not end within the bound is
parked in a module-level list (Qt aborts the process if a running ``QThread`` is destroyed).
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QMetaObject,
    QObject,
    Qt,
    QThread,
    Signal,
    Slot,
)

from thermalfea.core.errors import ThermalFEAError

_log = logging.getLogger(__name__)

#: Default bound [ms] of the waits that join a thread.
JOIN_TIMEOUT_MS = 10000

# Threads that did not end in time: kept alive so Qt never destroys a running QThread.
_PARKED: list[Any] = []


class TaskCancelled(Exception):
    """Raised by a task function that stopped because cancellation was requested."""


class TaskContext:
    """What a task function receives: progress reporting and the cancellation flag.

    Attributes
    ----------
    cancel_event : threading.Event
        Set when cancellation is requested (thread-safe).
    """

    def __init__(self, cancel_event: threading.Event, emit: Callable[[object], None]) -> None:
        self.cancel_event = cancel_event
        self._emit = emit

    @property
    def cancelled(self) -> bool:
        """``True`` once cancellation was requested."""
        return self.cancel_event.is_set()

    def report(self, info: object) -> bool:
        """Publish progress to the GUI.

        Parameters
        ----------
        info : object
            Delivered by the ``progress`` signal.

        Returns
        -------
        bool
            ``True`` to go on, ``False`` if cancellation was requested (the shape of a
            solver progress callback).
        """
        self._emit(info)
        return not self.cancel_event.is_set()


class _Runner(QObject):
    """Runs the task function in whatever thread it was moved to. Touches no widget."""

    progress = Signal(object)
    returned = Signal(object)
    raised = Signal(object)
    stopped = Signal(object)

    def __init__(self, fn: Callable[[TaskContext], Any], cancel_event: threading.Event) -> None:
        super().__init__()
        self._fn = fn
        self._cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        """Run the function and emit exactly one terminal signal."""
        context = TaskContext(self._cancel_event, self.progress.emit)
        try:
            value = self._fn(context)
        except TaskCancelled:
            self.stopped.emit(None)
        except BaseException as exc:  # noqa: BLE001 (delivered to the GUI, never lost)
            self.raised.emit(exc)
        else:
            if self._cancel_event.is_set():
                self.stopped.emit(value)
            else:
                self.returned.emit(value)


class BackgroundTask(QObject):
    """Handle of one background job.

    Parameters
    ----------
    fn : callable
        ``fn(context: TaskContext) -> value``, run in the worker thread.
    parent : QObject, optional
    executor : SerialWorker, optional
        Run on this long-lived thread instead of a thread of its own.
    name : str
        Used in log messages.

    Attributes
    ----------
    result : object
        The return value of the last finished (or cancelled) run.
    error : Exception or None
        The exception of a failed run.
    """

    started = Signal()
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)

    def __init__(
        self,
        fn: Callable[[TaskContext], Any],
        parent: QObject | None = None,
        *,
        executor: SerialWorker | None = None,
        name: str = "task",
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.result: Any = None
        self.error: Exception | None = None
        self._executor = executor
        self._cancel_event = threading.Event()
        self._runner = _Runner(fn, self._cancel_event)
        self._thread: QThread | None = None
        self._outcome: tuple[str, Any] | None = None
        self._ended = False
        self._started = False
        queued = Qt.ConnectionType.QueuedConnection
        self._runner.progress.connect(self._on_progress, queued)
        self._runner.returned.connect(self._on_returned, queued)
        self._runner.raised.connect(self._on_raised, queued)
        self._runner.stopped.connect(self._on_stopped, queued)

    # ------------------------------------------------------------------ control
    @property
    def running(self) -> bool:
        """``True`` from :meth:`start` until the terminal signal was emitted."""
        return self._started and not self._ended

    def start(self) -> None:
        """Hand the job to its thread. A task is run once."""
        if self._started:
            raise RuntimeError("a background task can be started only once")
        self._started = True
        if self._executor is not None:
            self._executor.submit(self._runner)
        else:
            thread = QThread()
            self._thread = thread
            self._runner.moveToThread(thread)
            thread.started.connect(self._runner.run, Qt.ConnectionType.QueuedConnection)
            thread.finished.connect(self._on_thread_finished, Qt.ConnectionType.QueuedConnection)
            thread.start()
        self.started.emit()

    @property
    def thread_alive(self) -> bool:
        """True while the task's own thread (if it has one) is still running."""
        return self._thread is not None and self._thread.isRunning()

    def cancel(self) -> None:
        """Ask the task to stop (cooperative; safe to call from any thread)."""
        self._cancel_event.set()

    @property
    def cancel_requested(self) -> bool:
        """``True`` once :meth:`cancel` was called."""
        return self._cancel_event.is_set()

    def wait(self, timeout_ms: int = JOIN_TIMEOUT_MS) -> bool:
        """Wait (bounded) until the task has ended and its terminal signal was emitted.

        Pending signals are delivered while waiting, so this also works from the GUI
        thread without a running event loop.

        Returns
        -------
        bool
            ``True`` if the task has ended.
        """
        timer = QElapsedTimer()
        timer.start()
        while not self._ended and timer.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
            if self._thread is not None:
                self._thread.wait(10)
            else:
                QThread.msleep(5)
        return self._ended

    def shutdown(self, timeout_ms: int = JOIN_TIMEOUT_MS) -> bool:
        """Cancel and wait (bounded) for the end of the task.

        Returns
        -------
        bool
            ``True`` if the task has ended (or never started).
        """
        if not self._started:
            return True
        self.cancel()
        return self.wait(timeout_ms)

    # ------------------------------------------------------------------- events
    @Slot(object)
    def _on_progress(self, info: object) -> None:
        if not self._ended:
            self.progress.emit(info)

    @Slot(object)
    def _on_returned(self, value: object) -> None:
        self._terminal("finished", value)

    @Slot(object)
    def _on_stopped(self, value: object) -> None:
        self._terminal("cancelled", value)

    @Slot(object)
    def _on_raised(self, exc: object) -> None:
        self._terminal("failed", exc)

    def _terminal(self, kind: str, payload: Any) -> None:
        self._outcome = (kind, payload)
        if self._thread is not None:
            self._thread.quit()  # the outcome is emitted when the thread has finished
        else:
            self._deliver()

    @Slot()
    def _on_thread_finished(self) -> None:
        thread = self._thread
        if thread is not None and not thread.wait(JOIN_TIMEOUT_MS):
            _PARKED.append(thread)
            _log.error("background task %r: its thread did not end", self.name)
        self._deliver()

    def _deliver(self) -> None:
        if self._ended or self._outcome is None:
            return
        kind, payload = self._outcome
        self._ended = True
        if kind == "failed":
            self.error = payload
            if isinstance(payload, ThermalFEAError):
                _log.error("%s failed: %s", self.name, payload)
            else:
                text = "".join(
                    traceback.format_exception(type(payload), payload, payload.__traceback__)
                )
                _log.error("%s failed with an unexpected error:\n%s", self.name, text)
            self.failed.emit(payload)
        else:
            self.result = payload
            getattr(self, kind).emit(payload)
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None


class SerialWorker(QObject):
    """One long-lived thread that runs jobs one after the other.

    Used for everything that must stay on a single thread for the life of the process
    (gmsh: build and mesh). Jobs are queued by :meth:`submit` and run in submission order.

    Parameters
    ----------
    parent : QObject, optional
    name : str
        Thread name.
    """

    def __init__(self, parent: QObject | None = None, name: str = "serial-worker") -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName(name)
        self._pending = 0
        self._lock = threading.Lock()
        self._thread.start()

    @property
    def busy(self) -> bool:
        """``True`` while a submitted job has not finished."""
        with self._lock:
            return self._pending > 0

    @property
    def is_running(self) -> bool:
        """``True`` while the thread is alive."""
        return self._thread.isRunning()

    def submit(self, runner: _Runner) -> None:
        """Queue a runner (called by :meth:`BackgroundTask.start`)."""
        with self._lock:
            self._pending += 1
        runner.moveToThread(self._thread)
        for signal in (runner.returned, runner.raised, runner.stopped):
            signal.connect(self._job_done, Qt.ConnectionType.QueuedConnection)
        QMetaObject.invokeMethod(runner, "run", Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _job_done(self, _payload: object) -> None:
        with self._lock:
            self._pending = max(0, self._pending - 1)

    def shutdown(self, timeout_ms: int = JOIN_TIMEOUT_MS) -> bool:
        """Stop the thread after the jobs already queued, waiting a bounded time.

        Returns
        -------
        bool
            ``True`` if the thread has ended.
        """
        self._thread.quit()
        if self._thread.wait(timeout_ms):
            return True
        _PARKED.append(self._thread)
        _log.error("%s: the thread did not end within %d ms", self._thread.objectName(),
                   timeout_ms)
        return False
