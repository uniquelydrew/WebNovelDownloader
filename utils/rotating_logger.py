from pathlib import Path
from datetime import datetime
import json
import threading


class LineRotatingJSONLogger:
    def __init__(self, path: str, max_lines: int = 5000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_lines = max_lines
        self._lock = threading.Lock()

    def log(self, stage: str, event: str, meta: dict | None = None):
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "stage": stage,
            "event": event,
            "meta": meta or {}
        }

        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            if self.path.exists():
                lines = self.path.read_text(encoding="utf-8").splitlines()
            else:
                lines = []

            lines.append(line)

            if len(lines) > self.max_lines:
                overflow = len(lines) - self.max_lines
                lines = lines[overflow:]

            self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
