from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from gui.adapters.tree_adapter import TreeAdapter


class SelectionController(QObject):
    def __init__(self, tree_adapter: TreeAdapter, parent=None):
        super().__init__(parent)
        self.tree_adapter = tree_adapter
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._flush_autosave)
        self._autosave_callback: Callable[[], None] | None = None

    def set_autosave_callback(self, callback: Callable[[], None]) -> None:
        self._autosave_callback = callback

    def apply_saved_selection(self, selection: dict) -> None:
        self.tree_adapter.apply_selection(
            set(selection.get("selected_volume_indices", []) or []),
            set(selection.get("selected_chapter_urls", []) or []),
        )

    def handle_item_changed(self, item: QTreeWidgetItem) -> None:
        self.tree_adapter.propagate_item_state(item)
        self.schedule_autosave()

    def schedule_autosave(self, delay_ms: int = 600) -> None:
        self.autosave_timer.start(delay_ms)

    def _flush_autosave(self) -> None:
        if self._autosave_callback is not None:
            self._autosave_callback()

    def collect_selection_state(self) -> dict:
        return self.tree_adapter.collect_selection_state()

    def collect_export_payload(self) -> dict:
        return self.tree_adapter.collect_export_payload()
