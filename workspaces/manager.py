from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

class WorkspaceError(Exception):
    """Raised when workspace initialization or persistence fails."""
    pass

def _utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_slug(text: str, max_len: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "series"
    return text[:max_len].strip("-") or "series"


def series_id_from_url(url: str) -> str:
    """Deterministic series id based on URL path.

    Keeps human readability (slug) while avoiding collisions by appending a short
    hash of the full URL.
    """
    parsed = urlparse(url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    slug = _safe_slug(parts[-1] if parts else (parsed.netloc or "series"))
    # Short stable hash suffix
    import hashlib

    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{h}"


def get_default_workspace_root() -> Path:
    """User-profile scoped workspace root.

    Windows: %LOCALAPPDATA%\WebNovelScraper\workspaces
    Other:   ~/.webnovel_scraper/workspaces

    Override with WNS_WORKSPACE_ROOT.
    """
    override = os.getenv("WNS_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "WebNovelScraper" / "workspaces"

    return Path.home() / ".webnovel_scraper" / "workspaces"


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to temp in same directory for atomic replace.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        tmp = Path(f.name)
    tmp.replace(path)


@dataclass
class WorkspacePaths:
    root_dir: Path
    series_dir: Path
    workspace_json: Path
    tree_json: Path
    discovery_state_json: Path


class WorkspaceManager:
    """Incremental workspace persistence.

    Files are created immediately after index URL is verified.
    Tree is updated incrementally (by volume).
    """

    def __init__(
        self,
        series_url: str,
        series_title: str | None = None,
        series_id: str | None = None,
        workspace_root: Path | None = None,
    ):
        self.series_url = series_url
        self.series_id = series_id or series_id_from_url(series_url)
        self.workspace_root = (workspace_root or get_default_workspace_root()).resolve()

        series_dir = self.workspace_root / self.series_id
        self.paths = WorkspacePaths(
            root_dir=self.workspace_root,
            series_dir=series_dir,
            workspace_json=series_dir / "workspace.json",
            tree_json=series_dir / "tree.json",
            discovery_state_json=series_dir / "discovery_state.json",
        )

        self._ensure_initialized(series_title=series_title)

    def _ensure_initialized(self, series_title: str | None) -> None:
        self.paths.series_dir.mkdir(parents=True, exist_ok=True)

        if not self.paths.workspace_json.exists():
            ws = {
                "schema": 1,
                "series_id": self.series_id,
                "series_url": self.series_url,
                "series_title": series_title or None,
                "created": _utc_iso(),
                "last_updated": None,
                "volumes_discovered": 0,
                "ui_state": {},
                "selected_chapters": [],
            }
            _atomic_write_json(self.paths.workspace_json, ws)

        if not self.paths.tree_json.exists():
            _atomic_write_json(self.paths.tree_json, {"schema": 1, "volumes": []})

        if not self.paths.discovery_state_json.exists():
            st = {
                "schema": 1,
                "series_id": self.series_id,
                "series_url": self.series_url,
                "started": _utc_iso(),
                "completed": False,
                "last_volume_index_written": 0,
                "last_error": None,
            }
            _atomic_write_json(self.paths.discovery_state_json, st)

    def update_series_title(self, title: str) -> None:
        ws = self._read_json(self.paths.workspace_json, default={})
        if ws.get("series_title") != title:
            ws["series_title"] = title
            ws["last_updated"] = _utc_iso()
            _atomic_write_json(self.paths.workspace_json, ws)

    def append_volume(self, title: str, chapters: list[dict[str, Any]]) -> None:
        """Append a fully collected volume and persist immediately."""
        tree = self._read_json(self.paths.tree_json, default={"schema": 1, "volumes": []})
        vols = tree.get("volumes") or []
        vols.append({"title": title, "chapters": chapters})
        tree["volumes"] = vols
        tree["schema"] = tree.get("schema") or 1
        _atomic_write_json(self.paths.tree_json, tree)

        ws = self._read_json(self.paths.workspace_json, default={})
        ws["volumes_discovered"] = int(ws.get("volumes_discovered") or 0) + 1
        ws["last_updated"] = _utc_iso()
        _atomic_write_json(self.paths.workspace_json, ws)

        st = self._read_json(self.paths.discovery_state_json, default={})
        st["last_volume_index_written"] = int(st.get("last_volume_index_written") or 0) + 1
        st["last_error"] = None
        _atomic_write_json(self.paths.discovery_state_json, st)

    def mark_completed(self) -> None:
        st = self._read_json(self.paths.discovery_state_json, default={})
        st["completed"] = True
        st["completed_ts"] = _utc_iso()
        st["last_error"] = None
        _atomic_write_json(self.paths.discovery_state_json, st)

    def mark_error(self, err: str) -> None:
        st = self._read_json(self.paths.discovery_state_json, default={})
        st["completed"] = False
        st["last_error"] = err
        st["error_ts"] = _utc_iso()
        _atomic_write_json(self.paths.discovery_state_json, st)

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
