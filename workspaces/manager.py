from __future__ import annotations



import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


class WorkspaceError(Exception):
    """Raised when workspace initialization or persistence fails."""


def _utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_slug(text: str, max_len: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "series"
    return (text[:max_len].strip("-") or "series")


def series_id_from_url(url: str) -> str:
    """Deterministic series id based on URL path, with a short stable hash suffix."""
    parsed = urlparse(url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    slug = _safe_slug(parts[-1] if parts else (parsed.netloc or "series"))
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{h}"


def get_default_workspace_root() -> Path:
    """User-profile scoped workspace root.

    Windows: %LOCALAPPDATA%\\WebNovelScraper\\workspaces
    Other:   ~/.webnovel_scraper/workspaces

    Override with WNS_WORKSPACE_ROOT.
    """
    override = os.getenv("WNS_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return (Path(local_appdata) / "WebNovelScraper" / "workspaces").resolve()

    return (Path.home() / ".webnovel_scraper" / "workspaces").resolve()


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    workspace_json: Path
    tree_json: Path
    epub_root: Path  # unpacked EPUB project dir (contains mimetype, META-INF, OEBPS)


class WorkspaceManager:
    """Workspace manager backed by an unpacked EPUB project directory.

    Supports two usage modes:
      1) Manager-only (GUI): WorkspaceManager() then paths_for/load/open_workspace_file.
      2) Handle-bound (discovery): WorkspaceManager(series_url=..., series_title=...) then
         update_series_title/append_volume/mark_* methods.
    """

    def __init__(
            self,
            series_url: Optional[str] = None,
            series_title: Optional[str] = None,
            workspace_root: Optional[Path] = None,
            series_id: Optional[str] = None,
    ):
        self.workspaces_root = (workspace_root or get_default_workspace_root()).resolve()
        self._series_url = series_url
        self._series_id = series_id or (series_id_from_url(series_url) if series_url else None)

        if series_url:
            self.paths = self.paths_for(series_url)
            self._ensure_initialized(series_url=series_url, series_title=series_title)

    def paths_for(self, series_url: str, series_title: Optional[str] = None) -> WorkspacePaths:
        sid = series_id_from_url(series_url)
        root = (self.workspaces_root / sid).resolve()
        return WorkspacePaths(
            root=root,
            workspace_json=root / "workspace.json",
            tree_json=root / "tree.json",
            epub_root=root / "epub",
        )

    def open_workspace_file(self, workspace_json_path: Path) -> tuple[dict, dict]:
        ws = _read_json(workspace_json_path, default={})
        root = workspace_json_path.parent.resolve()
        tree = _read_json(root / "tree.json", default={"schema": 1, "volumes": []})
        return ws, tree

    def load(self, series_url: str, series_title: Optional[str] = None) -> tuple[dict, dict]:
        paths = self.paths_for(series_url)
        if not paths.workspace_json.exists():
            raise WorkspaceError(f"No workspace found for {series_url}")
        ws = _read_json(paths.workspace_json, default={})
        tree = _read_json(paths.tree_json, default={"schema": 1, "volumes": []})
        return ws, tree

    def ensure(self, series_url: str, series_title: Optional[str] = None) -> WorkspacePaths:
        paths = self.paths_for(series_url)
        self._ensure_initialized(series_url=series_url, series_title=series_title)
        return paths

    def create_or_update_from_payload(self, payload: dict) -> WorkspacePaths:
        """Create/update a workspace from a discovery payload (series_url/title/volumes)."""
        series_url = str(payload.get("series_url") or "").strip()
        series_title = (payload.get("series_title") or None)
        if not series_url:
            raise WorkspaceError("Payload missing series_url")
        paths = self.ensure(series_url, str(series_title) if series_title else None)

        # Write tree.json as payload mirror (schema=1)
        tree = {
            "schema": 1,
            "series_url": series_url,
            "series_title": series_title,
            "volumes": payload.get("volumes") or [],
        }
        _atomic_write_json(paths.tree_json, tree)

        # Update workspace.json minimal metadata (do not overwrite chapters index)
        ws = _read_json(paths.workspace_json, default={})
        ws["schema"] = int(ws.get("schema") or 2)
        ws["series_url"] = series_url
        if series_title:
            ws["series_title"] = series_title
        ws["last_updated"] = _utc_iso()
        if "selection" not in ws:
            ws["selection"] = {"selected_volume_indices": [], "selected_chapter_urls": []}
        if "chapters" not in ws:
            ws["chapters"] = []
        if "chapters_by_url" not in ws:
            ws["chapters_by_url"] = {}
        if "chapters_by_global" not in ws:
            ws["chapters_by_global"] = {}
        if "issues" not in ws:
            ws["issues"] = []
        _atomic_write_json(paths.workspace_json, ws)

        return paths

    def merge_payloads(self, old: dict, new: dict) -> dict:
        """Merge discovery payloads; prefer new but keep any previously-seen chapter URLs/titles."""
        if not isinstance(old, dict):
            return new
        if not isinstance(new, dict):
            return old

        merged = dict(new)
        merged.setdefault("series_url", old.get("series_url"))
        merged.setdefault("series_title", old.get("series_title"))

        old_vols = old.get("volumes") or []
        new_vols = new.get("volumes") or []

        out_vols: list[dict] = []
        for i, v in enumerate(new_vols):
            ov = old_vols[i] if i < len(old_vols) else {}
            mv = dict(v)
            mv.setdefault("title", ov.get("title"))
            # merge chapters by url
            ocs = {(c.get("url") or ""): c for c in (ov.get("chapters") or []) if isinstance(c, dict)}
            ncs = []
            for c in (v.get("chapters") or []):
                if not isinstance(c, dict):
                    continue
                url = (c.get("url") or "").strip()
                oc = ocs.get(url) or {}
                mc = dict(c)
                mc.setdefault("title", oc.get("title"))
                ncs.append(mc)
            mv["chapters"] = ncs
            out_vols.append(mv)

        # include old trailing volumes if new didn't have them
        if len(old_vols) > len(new_vols):
            out_vols.extend(old_vols[len(new_vols):])

        merged["volumes"] = out_vols
        return merged

    def update_selection(
            self,
            *,
            series_url: str,
            series_title: Optional[str],
            selected_volume_indices: list[int],
            selected_chapter_urls: list[str],
    ) -> None:
        paths = self.ensure(series_url, series_title)
        ws = _read_json(paths.workspace_json, default={})
        ws["series_url"] = series_url
        if series_title:
            ws["series_title"] = series_title
        ws["selection"] = {
            "selected_volume_indices": list(selected_volume_indices),
            "selected_chapter_urls": list(selected_chapter_urls),
        }
        ws["last_updated"] = _utc_iso()
        _atomic_write_json(paths.workspace_json, ws)

    # ----- discovery-compatible helpers (handle-bound) -----

    def _ensure_initialized(self, series_url: str, series_title: Optional[str]) -> None:
        paths = self.paths_for(series_url)
        paths.root.mkdir(parents=True, exist_ok=True)

        # schema=2: adds epub workspace + per-chapter index
        if not paths.workspace_json.exists():
            ws = {
                "schema": 2,
                "series_id": series_id_from_url(series_url),
                "series_url": series_url,
                "series_title": series_title or None,
                "created": _utc_iso(),
                "last_updated": None,
                "selection": {"selected_volume_indices": [], "selected_chapter_urls": []},
                # Canonical chapter index (see workspaces/epub_project.py)
                "chapters": [],
                "chapters_by_url": {},
                "chapters_by_global": {},
                "issues": [],
            }
            _atomic_write_json(paths.workspace_json, ws)

        if not paths.tree_json.exists():
            # discovery payload mirror for GUI convenience
            _atomic_write_json(paths.tree_json,
                               {"schema": 1, "series_url": series_url, "series_title": series_title or None,
                                "volumes": []})

        # Initialize unpacked EPUB directory structure lazily (created by epub_project)
        paths.epub_root.mkdir(parents=True, exist_ok=True)

    def update_series_title(self, title: str) -> None:
        if not self._series_url:
            raise WorkspaceError("update_series_title requires a handle-bound WorkspaceManager(series_url=...)")
        paths = self.paths_for(self._series_url)
        ws = _read_json(paths.workspace_json, default={})
        if ws.get("series_title") != title:
            ws["series_title"] = title
            ws["last_updated"] = _utc_iso()
            _atomic_write_json(paths.workspace_json, ws)

        tree = _read_json(paths.tree_json, default={"schema": 1, "volumes": []})
        tree["series_title"] = title
        tree["series_url"] = self._series_url
        _atomic_write_json(paths.tree_json, tree)

    def append_volume(self, title: str, chapters: list[dict[str, Any]]) -> None:
        """Append a fully collected volume into tree.json during discovery."""
        if not self._series_url:
            raise WorkspaceError("append_volume requires a handle-bound WorkspaceManager(series_url=...)")
        paths = self.paths_for(self._series_url)
        tree = _read_json(paths.tree_json, default={"schema": 1, "volumes": []})
        vols = tree.get("volumes") or []
        vols.append({"title": title, "chapters": chapters})
        tree["series_url"] = self._series_url
        tree["series_title"] = tree.get("series_title") or None
        tree["volumes"] = vols
        tree["schema"] = tree.get("schema") or 1
        _atomic_write_json(paths.tree_json, tree)

        ws = _read_json(paths.workspace_json, default={})
        ws["last_updated"] = _utc_iso()
        _atomic_write_json(paths.workspace_json, ws)



from pathlib import Path

from models.chapter import Chapter
from workspaces.epub_project import EpubWorkspaceProject


class EpubWorkspacePipeline:
    """Persist chapters into the workspace's unpacked EPUB project immediately."""

    def open_spider(self, spider):
        workspace_dir = getattr(spider, "workspace_dir", None)
        if not workspace_dir:
            raise RuntimeError("EpubWorkspacePipeline requires spider.workspace_dir")
        self.workspace_root = Path(workspace_dir).resolve()
        self.project = EpubWorkspaceProject(self.workspace_root)

        # Metadata optionally provided by CLI/shim.
        self.series_title = str(getattr(spider, "series_title", "") or "Unknown Series")
        self.language = str(getattr(spider, "language", "") or "en")

    def process_item(self, item, spider):
        assert isinstance(item, Chapter)

        self.project.write_chapter(
            series_title=item.novel_title or self.series_title,
            language=getattr(item, "language", None) or self.language,
            volume_index=item.volume_index,
            volume_title=item.volume_title,
            volume_chapter_index=item.chapter_index,
            global_index=getattr(item, "global_index", None),
            chapter_title_raw=item.chapter_title,
            url=item.chapter_url,
            text=item.text,
        )
        return item

