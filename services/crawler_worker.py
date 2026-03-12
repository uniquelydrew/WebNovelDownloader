from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from services.discovery_service import DiscoveryService


class CrawlerWorker(QThread):
    """Legacy compatibility worker.

    This class previously depended on a removed Scrapy spider. It now performs a
    discovery pass, selects every discovered chapter, and delegates crawling and
    export to the active subprocess pipeline used by the GUI.
    """

    progress_changed = Signal(int)
    status_message = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, index_url: str, output_dir: str, fmt: str):
        super().__init__()
        self.index_url = index_url
        self.output_dir = output_dir
        self.fmt = fmt
        self.project_root = Path(__file__).resolve().parents[1]

    def run(self):
        selection_path: str | None = None
        try:
            self.status_message.emit("Running discovery...")
            payload = DiscoveryService().load_series_from_url(self.index_url)
            selection = self._selection_from_payload(payload)
            total = int(selection.get("total_chapters") or 0)
            if total <= 0:
                self.finished_signal.emit(False, "No chapters were discovered.")
                return

            self.progress_changed.emit(0)
            self.status_message.emit(f"Starting export for {total} chapter(s)...")

            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                json.dump(selection, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                selection_path = handle.name

            cmd = [
                sys.executable,
                str(self.project_root / "cli" / "run_crawl.py"),
                "--selection",
                selection_path,
                "--out-dir",
                self.output_dir,
                "--format",
                self.fmt,
            ]

            env = os.environ.copy()
            pythonpath = str(self.project_root)
            env["PYTHONPATH"] = pythonpath + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
            )

            for line in proc.stdout or []:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    self.status_message.emit(line)
                    continue

                etype = event.get("type")
                if etype == "progress":
                    done = int(event.get("done") or 0)
                    total = max(1, int(event.get("total") or total or 1))
                    pct = int((done / total) * 100)
                    self.progress_changed.emit(max(0, min(100, pct)))
                    self.status_message.emit(str(event.get("message") or f"Progress: {done}/{total}"))
                elif etype in {"status", "export"}:
                    self.status_message.emit(str(event.get("message") or event.get("path") or line))
                elif etype == "error":
                    self.status_message.emit(str(event.get("message") or "Unknown subprocess error"))
                else:
                    self.status_message.emit(line)

            rc = proc.wait()
            if rc == 0:
                self.progress_changed.emit(100)
                self.finished_signal.emit(True, "Export completed.")
            else:
                self.finished_signal.emit(False, f"Subprocess exited with code {rc}")
        except Exception as e:
            self.finished_signal.emit(False, f"{type(e).__name__}: {e}")
        finally:
            if selection_path:
                try:
                    os.unlink(selection_path)
                except Exception:
                    pass

    @staticmethod
    def _selection_from_payload(payload: dict) -> dict:
        chapters: list[dict] = []
        for volume_index, volume in enumerate(payload.get("volumes") or [], start=1):
            volume_title = str(volume.get("title") or f"Volume {volume_index}").strip() or f"Volume {volume_index}"
            for chapter_index, chapter in enumerate(volume.get("chapters") or [], start=1):
                chapters.append(
                    {
                        "type": "chapter",
                        "volume_index": volume_index,
                        "volume_title": volume_title,
                        "chapter_index": chapter_index,
                        "chapter_title": str(chapter.get("title") or f"Chapter {chapter_index}").strip() or f"Chapter {chapter_index}",
                        "url": str(chapter.get("url") or "").strip(),
                    }
                )

        return {
            "series_title": str(payload.get("series_title") or "Unknown Series").strip() or "Unknown Series",
            "series_url": str(payload.get("series_url") or "").strip(),
            "chapters": chapters,
            "total_chapters": len(chapters),
        }
