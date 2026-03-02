from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QMessageBox, QProgressBar, QTreeWidget,
    QTreeWidgetItem, QTextEdit
)

from parsing.html_doc import HtmlDoc
from parsing.wuxiaworld_file_parser import WuxiaworldFileParser
from services.discovery_process import DiscoveryProcess
from services.subprocess_worker import SubprocessCrawlWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WebNovelScraper")
        self.resize(820, 640)

        self.series = None
        self.discovery_proc: DiscoveryProcess | None = None
        self.discovery_timer: QTimer | None = None

        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        main = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Index URL:"))
        self.url_input = QLineEdit()
        row1.addWidget(self.url_input, 1)
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self._load_index)
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

        self.browse_btn = QPushButton("Browse...")
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
        main.addWidget(self.tree, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        main.addWidget(self.log, 1)

        root.setLayout(main)
        self.setCentralWidget(root)

    def _append_log(self, msg: str) -> None:
        self.log.append(msg)

    def _select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Export Directory")
        if directory:
            self.dir_input.setText(directory)
            self._update_export_enabled()

    def _load_index(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a URL.")
            return

        self.load_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.tree.clear()
        self.progress.setValue(0)
        self._append_log(f"Starting discovery (browser auth + capture): {url}")

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
                QMessageBox.critical(self, "Error", result.get("error", "Unknown error"))
                self._append_log(f"Discovery failed: {result.get('error')}")
                return

            html = result.get("html", "")
            self._append_log(f"Discovery complete. Rendered HTML size: {len(html)} bytes")

            doc = HtmlDoc.from_html(html, url=self.url_input.text().strip())
            parser = WuxiaworldFileParser()
            self.series = parser.parse(doc)

            self._populate_tree()
            self._update_export_enabled()

    def _populate_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()

        if not self.series:
            self.tree.blockSignals(False)
            return

        root = QTreeWidgetItem([self.series.title])
        root.setFlags(root.flags() | Qt.ItemIsUserCheckable)
        root.setCheckState(0, Qt.Unchecked)
        root.setData(0, Qt.UserRole, {"type": "series"})
        self.tree.addTopLevelItem(root)

        for vol in self.series.volumes:
            vitem = QTreeWidgetItem([vol.title])
            vitem.setFlags(vitem.flags() | Qt.ItemIsUserCheckable)
            vitem.setCheckState(0, Qt.Unchecked)
            vitem.setData(0, Qt.UserRole, {"type": "volume", "volume_index": vol.index, "volume_title": vol.title})
            root.addChild(vitem)

            for cref in vol.chapters:
                citem = QTreeWidgetItem([cref.title])
                citem.setFlags(citem.flags() | Qt.ItemIsUserCheckable)
                citem.setCheckState(0, Qt.Unchecked)
                citem.setData(0, Qt.UserRole, {
                    "type": "chapter",
                    "volume_index": vol.index,
                    "volume_title": vol.title,
                    "chapter_index": cref.index,
                    "chapter_title": cref.title,
                    "url": cref.url,
                })
                vitem.addChild(citem)

        root.setExpanded(True)
        self.tree.blockSignals(False)

    def _on_item_changed(self, item, column):
        data = item.data(0, Qt.UserRole) or {}
        if data.get("type") in ("series", "volume"):
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, item.checkState(0))
        self._update_export_enabled()

    def _collect_selection(self):
        chapters = []
        if self.tree.topLevelItemCount() == 0:
            return {"chapters": [], "total_chapters": 0, "series_title": self.series.title if self.series else "Unknown"}

        root = self.tree.topLevelItem(0)

        def walk(node):
            data = node.data(0, Qt.UserRole) or {}
            if data.get("type") == "chapter" and node.checkState(0) == Qt.Checked:
                chapters.append(data)
            for i in range(node.childCount()):
                walk(node.child(i))

        walk(root)
        return {
            "series_title": self.series.title if self.series else "Unknown",
            "chapters": chapters,
            "total_chapters": len(chapters),
        }

    def _update_export_enabled(self):
        has_dir = bool(self.dir_input.text().strip())
        payload = self._collect_selection()
        self.export_btn.setEnabled(bool(self.series) and has_dir and payload.get("total_chapters", 0) > 0)

    def _export_selected(self):
        out_dir = self.dir_input.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Error", "Please select an export directory.")
            return

        payload = self._collect_selection()
        if payload["total_chapters"] == 0:
            QMessageBox.warning(self, "Error", "No chapters selected.")
            return

        fmt = self.format_select.currentText().strip()
        self._append_log(f"Export starting: {payload['total_chapters']} chapter(s), format={fmt}, out={out_dir}")

        self.progress.setRange(0, payload["total_chapters"])
        self.progress.setValue(0)

        self.export_btn.setEnabled(False)
        self.load_btn.setEnabled(False)

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
        self._update_export_enabled()
        self._append_log(msg)
        if ok:
            QMessageBox.information(self, "Done", msg)
        else:
            QMessageBox.critical(self, "Error", msg)
