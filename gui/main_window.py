from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from gui.adapters.tree_adapter import TreeAdapter
from gui.controllers.discovery_controller import DiscoveryController
from gui.controllers.export_controller import ExportController
from gui.controllers.selection_controller import SelectionController
from gui.controllers.workspace_controller import WorkspaceController
from workspaces.manager import WorkspaceManager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WebNovelScraper")
        self.resize(920, 700)

        self.project_root = Path(__file__).resolve().parents[1]
        self.series_payload: dict | None = None

        self._build_ui()

        self.workspace_controller = WorkspaceController(WorkspaceManager())
        self.tree_adapter = TreeAdapter(self.tree)
        self.discovery_controller = DiscoveryController(self)
        self.export_controller = ExportController()
        self.selection_controller = SelectionController(self.tree_adapter, self)
        self.selection_controller.set_autosave_callback(self._save_workspace_selection)

        self.tree.itemChanged.connect(self._on_item_changed)

    def _build_ui(self) -> None:
        self._build_menu()

        root = QWidget()
        main = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Index URL:"))
        self.url_input = QLineEdit()
        row1.addWidget(self.url_input, 1)

        self.open_ws_btn = QPushButton("Open Workspace…")
        self.open_ws_btn.clicked.connect(self._open_workspace_dialog)
        row1.addWidget(self.open_ws_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(lambda: self._load_index(force_refresh=True))
        row1.addWidget(self.refresh_btn)

        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(lambda: self._load_index(force_refresh=False))
        row1.addWidget(self.load_btn)
        main.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Format:"))
        self.format_select = QComboBox()
        self.format_select.addItems(["epub", "pdf"])
        row2.addWidget(self.format_select)

        row2.addWidget(QLabel("Export Dir:"))
        self.dir_input = QLineEdit()
        self.dir_input.textChanged.connect(self._update_export_enabled)
        row2.addWidget(self.dir_input, 1)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._select_directory)
        row2.addWidget(self.browse_btn)

        self.export_btn = QPushButton("Export Selected")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_selected)
        row2.addWidget(self.export_btn)
        main.addLayout(row2)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Volumes / Chapters"])
        main.addWidget(self.tree, 2)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        main.addWidget(self.log, 1)

        root.setLayout(main)
        self.setCentralWidget(root)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")

        act_open_ws = QAction("Open Workspace…", self)
        act_open_ws.triggered.connect(self._open_workspace_dialog)
        file_menu.addAction(act_open_ws)

        act_open_ws_dir = QAction("Open Workspace Folder…", self)
        act_open_ws_dir.triggered.connect(self._open_workspace_folder_dialog)
        file_menu.addAction(act_open_ws_dir)

        file_menu.addSeparator()

        act_refresh = QAction("Refresh from Web", self)
        act_refresh.triggered.connect(lambda: self._load_index(force_refresh=True))
        file_menu.addAction(act_refresh)

        file_menu.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

    def _append_log(self, msg: str) -> None:
        self.log.append(msg)

    def _set_busy(self, busy: bool) -> None:
        self.load_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled((not busy) and bool(self.series_payload))
        if busy:
            self.export_btn.setEnabled(False)
        else:
            self._update_export_enabled()

    def _select_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Export Directory")
        if directory:
            self.dir_input.setText(directory)

    def _open_workspace_folder_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Workspace Folder")
        if not directory:
            return
        workspace_json = Path(directory) / "workspace.json"
        if not workspace_json.exists():
            QMessageBox.warning(self, "Error", "Selected folder does not contain workspace.json")
            return
        self._open_workspace_path(workspace_json)

    def _open_workspace_dialog(self) -> None:
        start_dir = str(self.workspace_controller.ws_mgr.workspaces_root)
        path, _ = QFileDialog.getOpenFileName(self, "Open Workspace", start_dir, "Workspace (workspace.json)")
        if not path:
            return
        self._open_workspace_path(Path(path))

    def _open_workspace_path(self, workspace_json_path: Path) -> None:
        try:
            ws, tree, workspace_dir = self.workspace_controller.open_workspace_file(workspace_json_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open workspace: {type(e).__name__}: {e}")
            return
        self._load_workspace(ws, tree, workspace_dir)

    def _load_workspace(self, ws: dict, tree: dict, workspace_dir: Path) -> None:
        self.series_payload = tree
        url = (tree.get("series_url") or ws.get("series_url") or "").strip()
        if url:
            self.url_input.setText(url)
        title = (tree.get("series_title") or ws.get("series_title") or "Unknown Series").strip()
        self._append_log(f"Workspace loaded: {title} ({workspace_dir})")
        self.tree_adapter.populate_from_payload(tree)
        self.selection_controller.apply_saved_selection(ws.get("selection") or {})
        self.refresh_btn.setEnabled(True)
        self._update_export_enabled()

    def _load_index(self, force_refresh: bool) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a URL.")
            return

        if not force_refresh:
            try:
                loaded = self.workspace_controller.try_load_by_url(url)
                if loaded is not None:
                    ws, tree, workspace_dir = loaded
                    self._load_workspace(ws, tree, workspace_dir)
                    return
            except Exception:
                pass

        self._set_busy(True)
        self.tree_adapter.clear()
        self.progress.setValue(0)
        self.series_payload = None
        self._append_log(f"Starting discovery: {url}")
        self.discovery_controller.start(url, self._handle_discovery_result, force_refresh=force_refresh)

    def _handle_discovery_result(self, result: dict) -> None:
        self.load_btn.setEnabled(True)
        if not result.get("ok"):
            err = result.get("error", "Unknown error")
            self._append_log(f"Discovery failed: {err}")
            QMessageBox.critical(self, "Error", err)
            self._set_busy(False)
            return

        payload = result.get("payload")
        if not payload or not isinstance(payload, dict):
            self._append_log("Discovery returned no payload.")
            QMessageBox.critical(self, "Error", "Discovery returned no payload.")
            self._set_busy(False)
            return

        title = payload.get("series_title") or "Unknown Series"
        vcount = len(payload.get("volumes", []) or [])
        ccount = sum(len(v.get("chapters", []) or []) for v in (payload.get("volumes", []) or []))
        self._append_log(f"Discovery complete: {title} | volumes={vcount} | chapters={ccount}")

        try:
            payload, _workspace_dir, msg = self.workspace_controller.create_or_merge_from_payload(payload)
            self._append_log(msg)
        except Exception as e:
            self._append_log(f"Workspace update failed: {type(e).__name__}: {e}")

        self.series_payload = payload
        self.tree_adapter.populate_from_payload(payload)

        try:
            saved_selection = self.workspace_controller.load_saved_selection(payload)
            self.selection_controller.apply_saved_selection(saved_selection)
        except Exception:
            pass

        self.refresh_btn.setEnabled(True)
        self._set_busy(False)

    def _on_item_changed(self, item, _column) -> None:
        self.tree.blockSignals(True)
        try:
            self.selection_controller.handle_item_changed(item)
        finally:
            self.tree.blockSignals(False)
        self._update_export_enabled()

    def _save_workspace_selection(self) -> None:
        if not self.series_payload:
            return
        try:
            self.workspace_controller.update_selection(
                self.series_payload,
                self.selection_controller.collect_selection_state(),
            )
        except Exception as e:
            self._append_log(f"Workspace autosave failed: {type(e).__name__}: {e}")

    def _update_export_enabled(self) -> None:
        has_dir = bool(self.dir_input.text().strip())
        payload = self.selection_controller.collect_export_payload()
        self.export_btn.setEnabled(bool(self.series_payload) and has_dir and payload.get("total_chapters", 0) > 0)

    def _export_selected(self) -> None:
        out_dir = self.dir_input.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Error", "Please select an export directory.")
            return

        selection = self.selection_controller.collect_export_payload()
        if selection["total_chapters"] == 0:
            QMessageBox.warning(self, "Error", "No chapters selected.")
            return

        fmt = self.format_select.currentText().strip()
        self._save_workspace_selection()
        self._append_log(f"Export starting: {selection['total_chapters']} chapter(s), format={fmt}, out={out_dir}")
        self.progress.setRange(0, selection["total_chapters"])
        self.progress.setValue(0)
        self._set_busy(True)

        payload = {
            "series_title": selection["series_title"],
            "series_url": (self.series_payload or {}).get("series_url"),
            "chapters": selection["chapters"],
            "total_chapters": selection["total_chapters"],
        }

        self.export_controller.start(
            payload,
            out_dir,
            fmt,
            on_progress=self._on_progress,
            on_status=self._append_log,
            on_log=self._append_log,
            on_finished=self._on_finished,
        )

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        if message:
            self._append_log(message)

    def _on_finished(self, ok: bool, msg: str) -> None:
        self._set_busy(False)
        self._append_log(msg)
        if ok:
            QMessageBox.information(self, "Done", msg)
        else:
            QMessageBox.critical(self, "Error", msg)
