from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from services.discovery_process import DiscoveryProcess


class DiscoveryController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.discovery_proc: DiscoveryProcess | None = None
        self.discovery_timer: QTimer | None = None

    def start(self, url: str, on_result: Callable[[dict], None], *, force_refresh: bool = False) -> None:
        self.cancel()
        self.discovery_proc = DiscoveryProcess(url, force_refresh=force_refresh)
        self.discovery_proc.start()
        self.discovery_timer = QTimer(self)
        self.discovery_timer.timeout.connect(lambda: self._poll(on_result))
        self.discovery_timer.start(200)

    def _poll(self, on_result: Callable[[dict], None]) -> None:
        if self.discovery_proc is None:
            return
        if self.discovery_proc.poll():
            result = self.discovery_proc.get_result()
            if self.discovery_timer is not None:
                self.discovery_timer.stop()
            self.discovery_proc.join()
            self.discovery_proc = None
            on_result(result)

    def cancel(self) -> None:
        if self.discovery_timer is not None:
            self.discovery_timer.stop()
            self.discovery_timer.deleteLater()
            self.discovery_timer = None
        if self.discovery_proc is not None:
            try:
                self.discovery_proc.join(timeout=0.1)
            except Exception:
                pass
            self.discovery_proc = None
