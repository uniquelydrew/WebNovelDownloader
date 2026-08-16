from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class WorkspaceTaskWorker(QThread):
    """Runs cached-workspace maintenance without freezing the GUI."""

    progress = Signal(int, int, str)
    finished = Signal(bool, object)

    def __init__(self, task: Callable[[Callable[[int, int, str], None]], dict]):
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            result = self._task(lambda done, total, message: self.progress.emit(done, total, message))
        except Exception as exc:
            self.finished.emit(False, f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(True, result)
