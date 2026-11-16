"""GUI test fixtures: force the offscreen Qt platform before any Qt import."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

from thermalfea.gui.main_window import MainWindow  # noqa: E402


class DialogRecorder:
    """Stands in for ``MainWindow.error_dialog`` and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, message: str) -> None:
        self.calls.append((title, message))


def make_settings(path: Path) -> QSettings:
    """Return an ini-file ``QSettings`` at ``path``."""
    return QSettings(str(path), QSettings.Format.IniFormat)


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    return tmp_path / "s.ini"


@pytest.fixture
def dialogs() -> DialogRecorder:
    return DialogRecorder()


@pytest.fixture
def window(qtbot, settings_path: Path, dialogs: DialogRecorder) -> MainWindow:
    win = MainWindow(settings=make_settings(settings_path))
    win.error_dialog = dialogs
    qtbot.addWidget(win)
    return win
