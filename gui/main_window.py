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
from gui.preferences_dialog import PreferencesDialog
from services.workspace_task_worker import WorkspaceTaskWorker
from utils.browser_runtime import browser_launch_url, ensure_managed_browser
from utils.preferences import AppPreferences, PreferencesService
from workspaces.manager import WorkspaceManager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WebNovelScraper")
        self.resize(920, 700)

        self.project_root = Path(__file__).resolve().parents[1]
        self.series_payload: dict | None = None
        self.preferences_service = PreferencesService()
        self.preferences = self.preferences_service.load()
        self.preferences_dialog: PreferencesDialog | None = None
        self.workspace_task_worker: WorkspaceTaskWorker | None = None
        self._window_actions: dict[str, QAction] = {}
        self._styled_widgets: dict[str, QWidget] = {}

        self._build_ui()

        self.workspace_controller = WorkspaceController(WorkspaceManager(workspace_root=self._workspace_root_path()))
        self.tree_adapter = TreeAdapter(self.tree)
        self.discovery_controller = DiscoveryController(self)
        self.export_controller = ExportController()
        self.selection_controller = SelectionController(self.tree_adapter, self)
        self.selection_controller.set_autosave_callback(self._save_workspace_selection)

        self.tree.itemChanged.connect(self._on_item_changed)
        self._register_windows_menu_actions()
        self._register_styled_widgets()
        self._apply_preferences()

    def _build_ui(self) -> None:
        self._build_menu()

        root = QWidget()
        root.setObjectName("main_root")
        main = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Index URL:"))
        self.url_input = QLineEdit()
        self.url_input.setObjectName("url_input")
        row1.addWidget(self.url_input, 1)

        self.browser_btn = QPushButton("Launch Browser")
        self.browser_btn.setObjectName("launch_browser_button")
        self.browser_btn.clicked.connect(lambda: self._launch_browser_for_current_url(show_dialog=True))
        row1.addWidget(self.browser_btn)

        self.open_ws_btn = QPushButton("Open Workspace...")
        self.open_ws_btn.setObjectName("open_workspace_button")
        self.open_ws_btn.clicked.connect(self._open_workspace_dialog)
        row1.addWidget(self.open_ws_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("refresh_button")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._check_for_latest)
        row1.addWidget(self.refresh_btn)

        self.fix_titles_btn = QPushButton("Repair Workspace")
        self.fix_titles_btn.setObjectName("fix_comment_metadata_button")
        self.fix_titles_btn.setEnabled(False)
        self.fix_titles_btn.clicked.connect(self._fix_chapter_titles)
        row1.addWidget(self.fix_titles_btn)

        self.load_btn = QPushButton("Load")
        self.load_btn.setObjectName("load_button")
        self.load_btn.clicked.connect(lambda: self._load_index(force_refresh=False))
        row1.addWidget(self.load_btn)
        main.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Format:"))
        self.format_select = QComboBox()
        self.format_select.setObjectName("format_select")
        self.format_select.addItems(["epub", "pdf"])
        row2.addWidget(self.format_select)

        row2.addWidget(QLabel("Download Tabs:"))
        self.download_tabs_select = QComboBox()
        self.download_tabs_select.setObjectName("download_tabs_select")
        self.download_tabs_select.addItems(["1", "2", "3", "4"])
        self.download_tabs_select.setCurrentText("4")
        self.download_tabs_select.setToolTip("Number of managed Chrome tabs used to fetch chapters concurrently.")
        row2.addWidget(self.download_tabs_select)

        row2.addWidget(QLabel("Export Dir:"))
        self.dir_input = QLineEdit()
        self.dir_input.setObjectName("dir_input")
        self.dir_input.textChanged.connect(self._update_export_enabled)
        row2.addWidget(self.dir_input, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setObjectName("browse_button")
        self.browse_btn.clicked.connect(self._select_directory)
        row2.addWidget(self.browse_btn)

        self.check_downloads_btn = QPushButton("Check Downloads")
        self.check_downloads_btn.setObjectName("check_downloads_button")
        self.check_downloads_btn.setEnabled(False)
        self.check_downloads_btn.clicked.connect(self._check_downloaded_chapters)
        row2.addWidget(self.check_downloads_btn)

        self.export_btn = QPushButton("Export Selected")
        self.export_btn.setObjectName("export_button")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_selected)
        row2.addWidget(self.export_btn)

        self.download_btn = QPushButton("Download Selected")
        self.download_btn.setObjectName("download_selected_button")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download_selected)
        row2.addWidget(self.download_btn)
        main.addLayout(row2)

        self.tree = QTreeWidget()
        self.tree.setObjectName("chapters_tree")
        self.tree.setHeaderLabels(["Volumes / Chapters", "Status"])
        main.addWidget(self.tree, 2)

        self.progress = QProgressBar()
        self.progress.setObjectName("progress_bar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setObjectName("log_output")
        self.log.setReadOnly(True)
        main.addWidget(self.log, 1)

        root.setLayout(main)
        self.setCentralWidget(root)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        edit_menu = self.menuBar().addMenu("Edit")
        self.windows_menu = self.menuBar().addMenu("Windows")

        act_launch_browser = QAction("Launch Managed Browser", self)
        act_launch_browser.triggered.connect(lambda: self._launch_browser_for_current_url(show_dialog=True))
        file_menu.addAction(act_launch_browser)

        act_open_browser_home = QAction("Open Managed Browser Home", self)
        act_open_browser_home.triggered.connect(self._launch_browser_home)
        file_menu.addAction(act_open_browser_home)

        file_menu.addSeparator()

        act_open_ws = QAction("Open Workspace...", self)
        act_open_ws.triggered.connect(self._open_workspace_dialog)
        file_menu.addAction(act_open_ws)

        act_open_ws_dir = QAction("Open Workspace Folder...", self)
        act_open_ws_dir.triggered.connect(self._open_workspace_folder_dialog)
        file_menu.addAction(act_open_ws_dir)

        file_menu.addSeparator()

        act_refresh = QAction("Refresh Latest Chapters", self)
        act_refresh.triggered.connect(self._check_for_latest)
        file_menu.addAction(act_refresh)

        act_fix_titles = QAction("Repair Workspace", self)
        act_fix_titles.triggered.connect(self._fix_chapter_titles)
        file_menu.addAction(act_fix_titles)

        act_check_downloads = QAction("Check Downloaded Chapters", self)
        act_check_downloads.triggered.connect(self._check_downloaded_chapters)
        file_menu.addAction(act_check_downloads)

        file_menu.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        act_preferences = QAction("Preferences", self)
        act_preferences.triggered.connect(self._open_preferences_dialog)
        edit_menu.addAction(act_preferences)

    def _append_log(self, msg: str) -> None:
        self.log.append(msg)

    def _set_busy(self, busy: bool) -> None:
        self.load_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled((not busy) and bool(self.series_payload))
        self.fix_titles_btn.setEnabled((not busy) and bool(self.series_payload) and self.workspace_controller.active_workspace_dir is not None)
        self.browser_btn.setEnabled(not busy)
        self.check_downloads_btn.setEnabled((not busy) and self.workspace_controller.active_workspace_dir is not None)
        self.download_btn.setEnabled((not busy) and bool(self.series_payload) and self.selection_controller.collect_export_payload().get("total_chapters", 0) > 0)
        self.download_tabs_select.setEnabled(not busy)
        if busy:
            self.export_btn.setEnabled(False)
        else:
            self._update_export_enabled()
        self._refresh_window_menu_state()

    def _workspace_root_path(self) -> Path | None:
        if not self.preferences.workspace_root:
            return None
        return Path(self.preferences.workspace_root).expanduser().resolve()

    def _replace_workspace_manager(self) -> None:
        current_root = self._workspace_root_path()
        active_workspace_dir = self.workspace_controller.active_workspace_dir
        self.workspace_controller = WorkspaceController(WorkspaceManager(workspace_root=current_root))
        self.workspace_controller.active_workspace_dir = active_workspace_dir

    def _register_windows_menu_actions(self) -> None:
        self._add_window_action("main_window", "Main Window", self._restore_main_window)
        self._add_window_action("preferences_window", "Preferences", self._restore_preferences_window)
        self._refresh_window_menu_state()

    def _add_window_action(self, key: str, title: str, callback) -> None:
        action = QAction(title, self)
        action.triggered.connect(callback)
        self.windows_menu.addAction(action)
        self._window_actions[key] = action

    def _refresh_window_menu_state(self) -> None:
        main_action = self._window_actions.get("main_window")
        if main_action is not None:
            main_action.setEnabled(True)
        pref_action = self._window_actions.get("preferences_window")
        if pref_action is not None:
            pref_action.setEnabled(True)

    def _restore_main_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _restore_preferences_window(self) -> None:
        if self.preferences_dialog is None:
            self._open_preferences_dialog()
            return
        self.preferences_dialog.showNormal()
        self.preferences_dialog.raise_()
        self.preferences_dialog.activateWindow()

    def _open_preferences_dialog(self) -> None:
        if self.preferences_dialog is None:
            self.preferences_dialog = PreferencesDialog(
                service=self.preferences_service,
                preferences=self.preferences,
                widget_labels=self._widget_labels(),
                parent=self,
            )
            self.preferences_dialog.preferences_saved.connect(self._handle_preferences_saved)
            self.preferences_dialog.destroyed.connect(lambda *_: self._clear_preferences_dialog())
        self.preferences_dialog.show()
        self.preferences_dialog.raise_()
        self.preferences_dialog.activateWindow()

    def _clear_preferences_dialog(self) -> None:
        self.preferences_dialog = None
        self._refresh_window_menu_state()

    def _widget_labels(self) -> dict[str, str]:
        return {
            "main_root": "Main Window Surface",
            "url_input": "Index URL Input",
            "launch_browser_button": "Launch Browser Button",
            "open_workspace_button": "Open Workspace Button",
            "refresh_button": "Refresh Button",
            "fix_comment_metadata_button": "Fix Comment Metadata Button",
            "load_button": "Load Button",
            "format_select": "Format Selector",
            "download_tabs_select": "Download Tabs Selector",
            "dir_input": "Export Directory Input",
            "browse_button": "Browse Button",
            "check_downloads_button": "Check Downloads Button",
            "export_button": "Export Selected Button",
            "download_selected_button": "Download Selected Button",
            "chapters_tree": "Volumes / Chapters Tree",
            "progress_bar": "Progress Bar",
            "log_output": "Log Output",
        }

    def _register_styled_widgets(self) -> None:
        self._styled_widgets = {
            "main_root": self.centralWidget(),
            "url_input": self.url_input,
            "launch_browser_button": self.browser_btn,
            "open_workspace_button": self.open_ws_btn,
            "refresh_button": self.refresh_btn,
            "fix_comment_metadata_button": self.fix_titles_btn,
            "load_button": self.load_btn,
            "format_select": self.format_select,
            "download_tabs_select": self.download_tabs_select,
            "dir_input": self.dir_input,
            "browse_button": self.browse_btn,
            "check_downloads_button": self.check_downloads_btn,
            "export_button": self.export_btn,
            "download_selected_button": self.download_btn,
            "chapters_tree": self.tree,
            "progress_bar": self.progress,
            "log_output": self.log,
        }

    def _apply_preferences(self) -> None:
        self._apply_widget_color_preferences()

    def _apply_widget_color_preferences(self) -> None:
        enabled = self.preferences.widget_colors_enabled
        for widget_id, widget in self._styled_widgets.items():
            if not enabled:
                widget.setStyleSheet("")
                continue
            pref = self.preferences.widget_colors.get(widget_id)
            if pref is None:
                widget.setStyleSheet("")
                continue
            parts: list[str] = []
            if pref.background:
                parts.append(f"background-color: {pref.background};")
            if pref.foreground:
                parts.append(f"color: {pref.foreground};")
            widget.setStyleSheet(" ".join(parts))

    def _handle_preferences_saved(self, preferences: AppPreferences) -> None:
        self.preferences = preferences
        self._replace_workspace_manager()
        self._apply_preferences()
        self._append_log("Preferences saved.")
        if self.preferences.workspace_root:
            self._append_log(f"Workspace root set to: {self.preferences.workspace_root}")

    def _launch_browser_home(self) -> None:
        self._launch_browser(browser_launch_url(), show_dialog=True)

    def _launch_browser_for_current_url(self, *, show_dialog: bool) -> bool:
        url = self.url_input.text().strip() or browser_launch_url()
        return self._launch_browser(url, show_dialog=show_dialog)

    def _launch_browser(self, url: str, *, show_dialog: bool) -> bool:
        try:
            result = ensure_managed_browser(open_url=url)
        except Exception as e:
            message = f"Failed to launch browser: {type(e).__name__}: {e}"
            self._append_log(message)
            if show_dialog:
                QMessageBox.critical(self, "Browser Launch Failed", message)
            return False

        if result.launched:
            message = f"Managed browser launched using {result.browser_executable}"
        elif result.already_running:
            message = f"Managed browser already available at {result.endpoint}"
        else:
            message = f"Managed browser ready at {result.endpoint}"

        self._append_log(message)
        self._append_log(f"Browser profile: {result.profile_dir}")
        if show_dialog:
            QMessageBox.information(self, "Browser Ready", message)
        return True

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
        self._populate_tree(tree)
        self.selection_controller.apply_saved_selection(ws.get("selection") or {})
        self.refresh_btn.setEnabled(True)
        self.fix_titles_btn.setEnabled(True)
        self.check_downloads_btn.setEnabled(True)
        self._update_export_enabled()

    def _load_index(self, force_refresh: bool) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a URL.")
            return

        if not self._launch_browser(url, show_dialog=False):
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
        self._populate_tree(payload)

        try:
            saved_selection = self.workspace_controller.load_saved_selection(payload)
            self.selection_controller.apply_saved_selection(saved_selection)
        except Exception:
            pass

        self.refresh_btn.setEnabled(True)
        self._set_busy(False)

    def _check_for_latest(self) -> None:
        if not self.series_payload or self.workspace_controller.active_workspace_dir is None:
            QMessageBox.warning(self, "No Workspace", "Load or refresh a workspace first.")
            return
        url = str(self.series_payload.get("series_url") or self.url_input.text()).strip()
        if not url:
            QMessageBox.warning(self, "Error", "The loaded workspace has no index URL.")
            return
        known_urls = [
            str(chapter.get("url") or "")
            for volume in (self.series_payload.get("volumes") or [])
            if isinstance(volume, dict)
            for chapter in (volume.get("chapters") or [])
            if isinstance(chapter, dict) and chapter.get("url")
        ]
        known_volume_titles = [
            str(volume.get("title") or "").strip()
            for volume in (self.series_payload.get("volumes") or [])
            if isinstance(volume, dict) and str(volume.get("title") or "").strip()
        ]
        if not known_urls:
            QMessageBox.warning(self, "No Chapters", "Use Refresh first so there is a chapter frontier to check.")
            return
        if not self._launch_browser(url, show_dialog=False):
            return
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self._append_log(f"Checking the latest chapter frontier: {url}")
        self.discovery_controller.start(
            url,
            self._handle_latest_result,
            latest_only=True,
            known_chapter_urls=known_urls,
            known_volume_titles=known_volume_titles,
        )

    def _handle_latest_result(self, result: dict) -> None:
        if not result.get("ok"):
            err = result.get("error", "Unknown error")
            self._append_log(f"Latest check failed: {err}")
            QMessageBox.critical(self, "Latest Check Failed", err)
            self.progress.setRange(0, 100)
            self._set_busy(False)
            return
        payload = result.get("payload")
        if not isinstance(payload, dict):
            self._append_log("Latest check returned no payload.")
            self.progress.setRange(0, 100)
            self._set_busy(False)
            return
        try:
            merged, added, _workspace_dir = self.workspace_controller.merge_latest_payload(payload)
            self.series_payload = merged
            self._populate_tree(merged)
            saved_selection = self.workspace_controller.load_saved_selection(merged)
            self.selection_controller.apply_saved_selection(saved_selection)
            message = f"Latest check complete: {added} new chapter(s) found."
            self._append_log(message)
            QMessageBox.information(self, "Latest Check", message)
        except Exception as e:
            message = f"Latest workspace update failed: {type(e).__name__}: {e}"
            self._append_log(message)
            QMessageBox.critical(self, "Latest Check Failed", message)
        finally:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self._set_busy(False)

    def _fix_chapter_titles(self) -> None:
        if not self.series_payload or self.workspace_controller.active_workspace_dir is None:
            QMessageBox.warning(self, "No Workspace", "Load or refresh a workspace first.")
            return
        self._set_busy(True)
        self.progress.setRange(0, 0)
        self._append_log("Repairing comment metadata and checking cached downloads...")
        self.workspace_task_worker = WorkspaceTaskWorker(
            lambda report_progress: self.workspace_controller.repair_active_workspace(on_progress=report_progress)
        )
        self.workspace_task_worker.progress.connect(self._on_progress)
        self.workspace_task_worker.finished.connect(self._on_comment_repair_finished)
        self.workspace_task_worker.start()

    def _on_comment_repair_finished(self, ok: bool, result: object) -> None:
        self.workspace_task_worker = None
        self._set_busy(False)
        self.progress.setRange(0, 100)
        if not ok:
            message = f"Comment-metadata repair failed: {result}"
            self._append_log(message)
            QMessageBox.critical(self, "Repair Failed", message)
            return
        report = result
        if not isinstance(report, dict) or not isinstance(report.get("comment_metadata"), dict) or not isinstance(report.get("download_check"), dict):
            message = "Workspace repair returned an invalid report."
            self._append_log(message)
            QMessageBox.critical(self, "Repair Failed", message)
            return
        metadata = report["comment_metadata"]
        download_check = report["download_check"]
        issues = list(download_check.get("issues") or [])
        message = (
            f"Workspace repair complete: sampled {metadata['sampled']} checkpoint(s), "
            f"scanned {metadata['scanned']} recent chapter(s), and removed {metadata['paragraphs']} marker(s) "
            f"from {metadata['chapters']} cached chapter(s). "
            f"Download scan checked {int(download_check.get('scanned') or 0)} cached chapter(s) and found {len(issues)} issue(s)."
        )
        self._append_log(message)
        if not issues:
            QMessageBox.information(self, "Workspace Repaired", message)
            return
        for issue in issues[:25]:
            self._append_log(f"[{issue.get('type') or 'unknown_issue'}] {issue.get('title') or 'Untitled Chapter'}")
        if len(issues) > 25:
            self._append_log(f"...and {len(issues) - 25} more issue(s).")
        choice = QMessageBox.question(
            self,
            "Re-download Problem Chapters?",
            f"{message}\n\nRe-download the {len({str(issue.get('url') or '').strip() for issue in issues if str(issue.get('url') or '').strip()})} affected chapter(s) now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice == QMessageBox.Yes:
            self._download_issue_chapters(issues)

    def _download_issue_chapters(self, issues: list[dict]) -> None:
        if not self.series_payload:
            return
        issue_urls = {str(issue.get("url") or "").strip() for issue in issues}
        issue_urls.discard("")
        chapters = [
            {
                "volume_index": volume_index,
                "volume_title": str(volume.get("title") or f"Volume {volume_index}"),
                "chapter_index": chapter_index,
                "chapter_title": str(chapter.get("title") or f"Chapter {chapter_index}"),
                "url": str(chapter.get("url") or "").strip(),
            }
            for volume_index, volume in enumerate(self.series_payload.get("volumes") or [], start=1)
            if isinstance(volume, dict)
            for chapter_index, chapter in enumerate(volume.get("chapters") or [], start=1)
            if isinstance(chapter, dict) and str(chapter.get("url") or "").strip() in issue_urls
        ]
        if not chapters:
            self._append_log("No affected URLs were present in the current chapter tree; re-download was not started.")
            QMessageBox.warning(self, "Re-download Unavailable", "The affected chapters are not present in the current chapter tree.")
            return
        if not self._launch_browser_for_current_url(show_dialog=False):
            return
        self.progress.setRange(0, len(chapters))
        self.progress.setValue(0)
        self._set_busy(True)
        self._append_log(f"Re-downloading {len(chapters)} chapter(s) flagged by workspace repair.")
        self.export_controller.start_download(
            {
                "series_title": str(self.series_payload.get("series_title") or "Unknown Series"),
                "series_url": self.series_payload.get("series_url"),
                "chapters": chapters,
                "total_chapters": len(chapters),
                "download_tabs": self._download_tabs(),
            },
            on_progress=self._on_progress,
            on_status=self._append_log,
            on_log=self._append_log,
            on_finished=self._on_download_finished,
        )

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
        self.check_downloads_btn.setEnabled(self.workspace_controller.active_workspace_dir is not None)
        self.download_btn.setEnabled(bool(self.series_payload) and payload.get("total_chapters", 0) > 0)

    def _populate_tree(self, payload: dict) -> None:
        self.tree_adapter.populate_from_payload(payload, self.workspace_controller.active_downloaded_urls())

    def _check_downloaded_chapters(self) -> None:
        if self.workspace_controller.active_workspace_dir is None:
            QMessageBox.warning(self, "No Workspace", "Load or refresh a workspace first.")
            return

        self._set_busy(True)
        self.progress.setRange(0, 0)
        self._append_log("Checking cached downloads...")
        self.workspace_task_worker = WorkspaceTaskWorker(
            lambda report_progress: self.workspace_controller.scan_active_workspace_downloads(on_progress=report_progress)
        )
        self.workspace_task_worker.progress.connect(self._on_progress)
        self.workspace_task_worker.finished.connect(self._on_download_check_finished)
        self.workspace_task_worker.start()

    def _on_download_check_finished(self, ok: bool, result: object) -> None:
        self.workspace_task_worker = None
        self._set_busy(False)
        self.progress.setRange(0, 100)
        if not ok:
            message = f"Download scan failed: {result}"
            self._append_log(message)
            QMessageBox.critical(self, "Scan Failed", message)
            return
        report = result
        if not isinstance(report, dict):
            message = "Download scan returned an invalid report."
            self._append_log(message)
            QMessageBox.critical(self, "Scan Failed", message)
            return

        scanned = int(report.get("scanned") or 0)
        issues = list(report.get("issues") or [])
        if not issues:
            message = f"Download check passed. Scanned {scanned} cached chapter(s) with no paywall artifacts or incomplete downloads."
            self._append_log(message)
            QMessageBox.information(self, "Downloads OK", message)
            return

        self._append_log(f"Download check found {len(issues)} issue(s) across {scanned} cached chapter(s).")
        for issue in issues[:25]:
            title = str(issue.get("title") or "Untitled Chapter")
            issue_type = str(issue.get("type") or "unknown_issue")
            extra = ""
            if issue_type == "too_short":
                extra = f" ({int(issue.get('chars') or 0)} chars)"
            self._append_log(f"[{issue_type}] {title}{extra}")
        if len(issues) > 25:
            self._append_log(f"...and {len(issues) - 25} more issue(s).")

        QMessageBox.warning(
            self,
            "Downloaded Chapters Need Attention",
            f"Found {len(issues)} issue(s) across {scanned} cached chapter(s). See the log for details.",
        )

    def _export_selected(self) -> None:
        out_dir = self.dir_input.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Error", "Please select an export directory.")
            return

        selection = self.selection_controller.collect_export_payload()
        if selection["total_chapters"] == 0:
            QMessageBox.warning(self, "Error", "No chapters selected.")
            return

        if not self._launch_browser_for_current_url(show_dialog=False):
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
            "download_tabs": self._download_tabs(),
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

    def _download_selected(self) -> None:
        selection = self.selection_controller.collect_export_payload()
        if selection["total_chapters"] == 0:
            QMessageBox.warning(self, "No Chapters", "Select one or more chapters to download.")
            return
        if not self._launch_browser_for_current_url(show_dialog=False):
            return
        self._save_workspace_selection()
        self.progress.setRange(0, selection["total_chapters"])
        self.progress.setValue(0)
        self._set_busy(True)
        payload = {
            "series_title": selection["series_title"],
            "series_url": (self.series_payload or {}).get("series_url"),
            "chapters": selection["chapters"],
            "total_chapters": selection["total_chapters"],
            "download_tabs": self._download_tabs(),
        }
        self._append_log(f"Downloading selected chapters: {selection['total_chapters']} requested using {self._download_tabs()} managed Chrome tab(s).")
        self.export_controller.start_download(
            payload,
            on_progress=self._on_progress,
            on_status=self._append_log,
            on_log=self._append_log,
            on_finished=self._on_download_finished,
        )

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        if message:
            self._append_log(message)

    def _download_tabs(self) -> int:
        try:
            return max(1, min(4, int(self.download_tabs_select.currentText())))
        except (TypeError, ValueError):
            return 1

    def _on_finished(self, ok: bool, msg: str) -> None:
        self._set_busy(False)
        self._append_log(msg)
        if ok:
            QMessageBox.information(self, "Done", msg)
        else:
            QMessageBox.critical(self, "Error", msg)

    def _on_download_finished(self, ok: bool, msg: str) -> None:
        self._set_busy(False)
        if self.series_payload:
            self._populate_tree(self.series_payload)
            try:
                saved_selection = self.workspace_controller.load_saved_selection(self.series_payload)
                self.selection_controller.apply_saved_selection(saved_selection)
            except Exception:
                pass
        self._append_log(msg)
        if ok:
            QMessageBox.information(self, "Download Complete", msg)
        else:
            QMessageBox.critical(self, "Download Failed", msg)
