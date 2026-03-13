from __future__ import annotations

import json
import os
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

from utils.app_paths import build_crawl_command, runtime_cwd


class SubprocessCrawlWorker(QThread):
    progress = Signal(int, int, str)
    status = Signal(str)
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, selection_payload: dict, out_dir: str, fmt: str):
        super().__init__()
        self.selection_payload = selection_payload
        self.out_dir = out_dir
        self.fmt = fmt

    def run(self):
        selection_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
                json.dump(self.selection_payload, f, ensure_ascii=False, indent=2)
                selection_path = f.name
        except Exception as e:
            self.finished.emit(False, f"Failed to write selection: {type(e).__name__}: {e}")
            return

        try:
            self.status.emit("Launching crawl subprocess...")
            cmd = [
                *build_crawl_command(),
                "--selection",
                selection_path,
                "--out-dir",
                self.out_dir,
                "--format",
                self.fmt,
            ]

            proc = subprocess.Popen(
                cmd,
                cwd=str(runtime_cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=os.environ.copy(),
            )

            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                    typ = obj.get("type")
                    if typ == "progress":
                        done = int(obj.get("done", 0))
                        total = int(obj.get("total", 1))
                        msg = str(obj.get("message", ""))
                        self.progress.emit(done, total, msg)
                    elif typ == "status":
                        self.status.emit(str(obj.get("message", "")))
                    elif typ == "export":
                        self.log.emit(f"Exported: {obj.get('path')}")
                    elif typ == "error":
                        self.log.emit(f"ERROR: {obj.get('message')}")
                    else:
                        self.log.emit(line)
                except Exception:
                    self.log.emit(line)

            rc = proc.wait()
            if rc == 0:
                self.finished.emit(True, "Completed.")
            else:
                self.finished.emit(False, f"Subprocess exited with code {rc}")
        finally:
            if selection_path:
                try:
                    os.unlink(selection_path)
                except Exception:
                    pass
