from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QMessageBox, QProgressBar, QTreeWidget,
    QTreeWidgetItem, QTextEdit
)

from services.discovery_process import DiscoveryProcess
from services.subprocess_worker import SubprocessCrawlWorker
from workspaces.manager import WorkspaceManager, WorkspaceError


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WebNovelScraper")
        self.resize(920, 700)

        self.project_root = Path(__file__).resolve().parents[1]
        self.ws_mgr = WorkspaceManager(self.project_root)

        self.series_payload: dict | None = None
        self.discovery_proc: DiscoveryProcess | None = None
        self.discovery_timer: QTimer | None = None

        self.active_workspace_dir: Path | None = None
        self._autosave_timer: QTimer | None = None

        self._build_ui()

    def _build_ui(self):
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
        self.tree.itemChanged.connect(self._on_item_changed)
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

    def _select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Export Directory")
        if directory:
            self.dir_input.setText(directory)
            self._update_export_enabled()

    def _open_workspace_folder_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Workspace Folder")
        if not directory:
            return

        workspace_json = Path(directory) / "workspace.json"
        if not workspace_json.exists():
            QMessageBox.warning(self, "Error", "Selected folder does not contain workspace.json")
            return

        try:
            ws, tree = self.ws_mgr.open_workspace_file(workspace_json)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open workspace: {type(e).__name__}: {e}")
            return

        self._load_workspace(ws, tree, workspace_dir=workspace_json.parent)

    def _open_workspace_dialog(self) -> None:
        start_dir = str(self.ws_mgr.workspaces_root)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Workspace",
            start_dir,
            "Workspace (workspace.json)",
        )
        if not path:
            return

        try:
            ws, tree = self.ws_mgr.open_workspace_file(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open workspace: {type(e).__name__}: {e}")
            return

        self._load_workspace(ws, tree, workspace_dir=Path(path).parent)

    def _load_workspace(self, ws: dict, tree: dict, workspace_dir: Path) -> None:
        self.series_payload = tree
        self.active_workspace_dir = workspace_dir

        url = (tree.get("series_url") or ws.get("series_url") or "").strip()
        if url:
            self.url_input.setText(url)

        title = (tree.get("series_title") or ws.get("series_title") or "Unknown Series").strip()

        self._append_log(f"Workspace loaded: {title} ({workspace_dir})")
        self._populate_tree_from_payload(tree)

        selection = (ws.get("selection") or {})
        selected_chapter_urls = set(selection.get("selected_chapter_urls", []) or [])
        selected_volume_indices = set(selection.get("selected_volume_indices", []) or [])

        self._apply_selection(selected_volume_indices, selected_chapter_urls)

        self.refresh_btn.setEnabled(True)
        self._update_export_enabled()

    def _load_index(self, force_refresh: bool) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a URL.")
            return

        # If workspace exists and we're not forcing refresh: load from disk fast.
        if not force_refresh:
            try:
                ws, tree = self.ws_mgr.load(url)
                self._load_workspace(ws, tree, workspace_dir=self.ws_mgr.paths_for(url).root)
                return
            except Exception:
                # No workspace / incompatible; fall through to discovery.
                pass

        self.load_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.tree.clear()
        self.progress.setValue(0)
        self.series_payload = None

        self._append_log(f"Starting discovery: {url}")

        self.discovery_proc = DiscoveryProcess(url)
        self.discovery_proc.start()

        self.discovery_timer = QTimer(self)
        self.discovery_timer.timeout.connect(self._poll_discovery)
        self.discovery_timer.start(200)

    def _poll_discovery(self):
        assert self.discovery_proc is not None
        if self.discovery_proc.poll():
            result = self.discovery_proc.get_result()
            self.discovery_timer.stop()
            self.discovery_proc.join()

            self.load_btn.setEnabled(True)

            if not result.get("ok"):
                err = result.get("error", "Unknown error")
                self._append_log(f"Discovery failed: {err}")
                QMessageBox.critical(self, "Error", err)
                return

            payload = result.get("payload")
            if not payload or not isinstance(payload, dict):
                self._append_log("Discovery returned no payload.")
                QMessageBox.critical(self, "Error", "Discovery returned no payload.")
                return

            self.series_payload = payload

            title = payload.get("series_title") or "Unknown Series"
            vcount = len(payload.get("volumes", []) or [])
            ccount = sum(len(v.get("chapters", []) or []) for v in (payload.get("volumes", []) or []))

            self._append_log(f"Discovery complete: {title} | volumes={vcount} | chapters={ccount}")

            # Workspace create/update (merge with existing tree when present)
            try:
                series_url = str(payload.get("series_url") or "").strip()
                if series_url:
                    try:
                        ws_old, tree_old = self.ws_mgr.load(series_url)
                        merged = self.ws_mgr.merge_payloads(tree_old, payload)
                        self.ws_mgr.create_or_update_from_payload(merged)
                        self.series_payload = merged
                        payload = merged
                        self._append_log("Workspace refreshed (merged payload).")
                    except Exception:
                        self.ws_mgr.create_or_update_from_payload(payload)
                        self._append_log("Workspace created.")

                    self.active_workspace_dir = self.ws_mgr.paths_for(series_url, payload.get("series_title")).root
            except Exception as e:
                self._append_log(f"Workspace update failed: {type(e).__name__}: {e}")

            self._populate_tree_from_payload(payload)

            # Restore selection from workspace if present
            try:
                series_url = str(payload.get("series_url") or "").strip()
                if series_url:
                    ws, _ = self.ws_mgr.load(series_url, payload.get("series_title"))
                    sel = (ws.get("selection") or {})
                    self._apply_selection(
                        set(sel.get("selected_volume_indices", []) or []),
                        set(sel.get("selected_chapter_urls", []) or []),
                    )
            except Exception:
                pass

            self.refresh_btn.setEnabled(True)
            self._update_export_enabled()

    def _populate_tree_from_payload(self, payload: dict):
        self.tree.blockSignals(True)
        self.tree.clear()

        series_title = payload.get("series_title") or "Unknown Series"

        root = QTreeWidgetItem([series_title])
        root.setFlags(root.flags() | Qt.ItemIsUserCheckable)
        root.setCheckState(0, Qt.Unchecked)
        root.setData(0, Qt.UserRole, {"type": "series"})
        self.tree.addTopLevelItem(root)

        volumes = payload.get("volumes", []) or []
        for vi, vol in enumerate(volumes, start=1):
            vtitle = (vol.get("title") or f"Volume {vi}").strip()

            vitem = QTreeWidgetItem([vtitle])
            vitem.setFlags(vitem.flags() | Qt.ItemIsUserCheckable)
            vitem.setCheckState(0, Qt.Unchecked)
            vitem.setData(0, Qt.UserRole, {"type": "volume", "volume_index": vi, "volume_title": vtitle})
            root.addChild(vitem)

            chapters = vol.get("chapters", []) or []
            for ci, ch in enumerate(chapters, start=1):
                ctitle = (ch.get("title") or f"Chapter {ci}").strip()
                curl = (ch.get("url") or "").strip()

                citem = QTreeWidgetItem([ctitle])
                citem.setFlags(citem.flags() | Qt.ItemIsUserCheckable)
                citem.setCheckState(0, Qt.Unchecked)
                citem.setData(
                    0,
                    Qt.UserRole,
                    {
                        "type": "chapter",
                        "volume_index": vi,
                        "volume_title": vtitle,
                        "chapter_index": ci,
                        "chapter_title": ctitle,
                        "url": curl,
                    },
                )
                vitem.addChild(citem)

        root.setExpanded(True)
        self.tree.blockSignals(False)

    def _apply_selection(self, selected_volume_indices: set[int], selected_chapter_urls: set[str]) -> None:
        if self.tree.topLevelItemCount() == 0:
            return

        self.tree.blockSignals(True)

        root = self.tree.topLevelItem(0)
        for i in range(root.childCount()):
            vitem = root.child(i)
            vdata = vitem.data(0, Qt.UserRole) or {}
            vi = int(vdata.get("volume_index") or 0)

            if vi in selected_volume_indices:
                vitem.setCheckState(0, Qt.Checked)
                for j in range(vitem.childCount()):
                    vitem.child(j).setCheckState(0, Qt.Checked)
                continue

            any_checked = False
            all_checked = vitem.childCount() > 0
            for j in range(vitem.childCount()):
                citem = vitem.child(j)
                cdata = citem.data(0, Qt.UserRole) or {}
                url = str(cdata.get("url") or "").strip()
                if url and url in selected_chapter_urls:
                    citem.setCheckState(0, Qt.Checked)
                    any_checked = True
                else:
                    citem.setCheckState(0, Qt.Unchecked)
                    all_checked = False

            if all_checked and vitem.childCount() > 0:
                vitem.setCheckState(0, Qt.Checked)
            elif any_checked:
                vitem.setCheckState(0, Qt.PartiallyChecked)
            else:
                vitem.setCheckState(0, Qt.Unchecked)

        self.tree.blockSignals(False)

    def _on_item_changed(self, item, column):
        data = item.data(0, Qt.UserRole) or {}
        if data.get("type") in ("series", "volume"):
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, item.checkState(0))

        self._update_export_enabled()
        self._schedule_workspace_autosave()

    def _schedule_workspace_autosave(self) -> None:
        if not self.series_payload:
            return
        series_url = str(self.series_payload.get("series_url") or "").strip()
        if not series_url:
            return

        if self._autosave_timer is None:
            self._autosave_timer = QTimer(self)
            self._autosave_timer.setSingleShot(True)
            self._autosave_timer.timeout.connect(self._save_workspace_selection)

        self._autosave_timer.start(600)

    def _save_workspace_selection(self) -> None:
        if not self.series_payload:
            return

        series_url = str(self.series_payload.get("series_url") or "").strip()
        series_title = str(self.series_payload.get("series_title") or "Unknown Series").strip()
        if not series_url:
            return

        sel = self._collect_selection_state()
        try:
            self.ws_mgr.update_selection(
                series_url=series_url,
                series_title=series_title,
                selected_volume_indices=sel["selected_volume_indices"],
                selected_chapter_urls=sel["selected_chapter_urls"],
            )
        except Exception as e:
            self._append_log(f"Workspace autosave failed: {type(e).__name__}: {e}")

    def _collect_selection_state(self) -> dict:
        selected_volume_indices: set[int] = set()
        selected_chapter_urls: set[str] = set()

        if self.tree.topLevelItemCount() == 0:
            return {"selected_volume_indices": [], "selected_chapter_urls": []}

        root = self.tree.topLevelItem(0)
        for i in range(root.childCount()):
            vitem = root.child(i)
            vdata = vitem.data(0, Qt.UserRole) or {}
            vi = int(vdata.get("volume_index") or 0)

            # Consider a volume selected if the volume item itself is checked.
            if vitem.checkState(0) == Qt.Checked:
                selected_volume_indices.add(vi)
                continue

            for j in range(vitem.childCount()):
                citem = vitem.child(j)
                if citem.checkState(0) != Qt.Checked:
                    continue
                cdata = citem.data(0, Qt.UserRole) or {}
                url = str(cdata.get("url") or "").strip()
                if url:
                    selected_chapter_urls.add(url)

        return {
            "selected_volume_indices": sorted(selected_volume_indices),
            "selected_chapter_urls": sorted(selected_chapter_urls),
        }

    def _collect_selection(self):
        chapters = []

        if self.tree.topLevelItemCount() == 0:
            return {"series_title": None, "chapters": [], "total_chapters": 0}

        root = self.tree.topLevelItem(0)

        def walk(node):
            data = node.data(0, Qt.UserRole) or {}
            if data.get("type") == "chapter" and node.checkState(0) == Qt.Checked:
                chapters.append(data)
            for i in range(node.childCount()):
                walk(node.child(i))

        walk(root)

        series_title = root.text(0)
        return {"series_title": series_title, "chapters": chapters, "total_chapters": len(chapters)}

    def _update_export_enabled(self):
        has_dir = bool(self.dir_input.text().strip())
        payload = self._collect_selection()
        self.export_btn.setEnabled(bool(self.series_payload) and has_dir and payload.get("total_chapters", 0) > 0)

    def _export_selected(self):
        out_dir = self.dir_input.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Error", "Please select an export directory.")
            return

        selection = self._collect_selection()
        if selection["total_chapters"] == 0:
            QMessageBox.warning(self, "Error", "No chapters selected.")
            return

        fmt = self.format_select.currentText().strip()

        # Persist selection prior to export
        self._save_workspace_selection()

        self._append_log(
            f"Export starting: {selection['total_chapters']} chapter(s), format={fmt}, out={out_dir}"
        )

        self.progress.setRange(0, selection["total_chapters"])
        self.progress.setValue(0)

        self.export_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        payload = {
            "series_title": selection["series_title"],
            "series_url": (self.series_payload or {}).get("series_url"),
            "chapters": selection["chapters"],
            "total_chapters": selection["total_chapters"],
        }

        self.worker = SubprocessCrawlWorker(payload, out_dir, fmt)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._append_log)
        self.worker.log.connect(self._append_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, done: int, total: int, message: str):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        if message:
            self._append_log(message)

    def _on_finished(self, ok: bool, msg: str):
        self.load_btn.setEnabled(True)
        self.refresh_btn.setEnabled(bool(self.series_payload))
        self._update_export_enabled()
        self._append_log(msg)
        if ok:
            QMessageBox.information(self, "Done", msg)
        else:
            QMessageBox.critical(self, "Error", msg)
