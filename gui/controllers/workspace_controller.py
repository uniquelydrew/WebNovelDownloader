from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from workspaces.epub_project import EpubWorkspaceProject
from workspaces.manager import WorkspaceManager


class WorkspaceController:
    def __init__(self, workspace_manager: WorkspaceManager):
        self.ws_mgr = workspace_manager
        self.active_workspace_dir: Path | None = None

    def open_workspace_file(self, workspace_json_path: Path) -> tuple[dict, dict, Path]:
        ws, tree = self.ws_mgr.open_workspace_file(workspace_json_path)
        self.active_workspace_dir = workspace_json_path.parent.resolve()
        return ws, tree, self.active_workspace_dir

    def try_load_by_url(self, series_url: str, series_title: str | None = None) -> tuple[dict, dict, Path] | None:
        ws, tree = self.ws_mgr.load(series_url, series_title)
        self.active_workspace_dir = self.ws_mgr.paths_for(series_url).root
        return ws, tree, self.active_workspace_dir

    def create_or_merge_from_payload(self, payload: dict) -> tuple[dict, Path | None, str]:
        series_url = str(payload.get("series_url") or "").strip()
        if not series_url:
            return payload, None, "No workspace URL available."

        try:
            _ws_old, tree_old = self.ws_mgr.load(series_url)
            merged = self.ws_mgr.merge_payloads(tree_old, payload)
            self.ws_mgr.create_or_update_from_payload(merged)
            self.active_workspace_dir = self.ws_mgr.paths_for(series_url, merged.get("series_title")).root
            return merged, self.active_workspace_dir, "Workspace refreshed (merged payload)."
        except Exception:
            self.ws_mgr.create_or_update_from_payload(payload)
            self.active_workspace_dir = self.ws_mgr.paths_for(series_url, payload.get("series_title")).root
            return payload, self.active_workspace_dir, "Workspace created."

    def merge_latest_payload(self, payload: dict) -> tuple[dict, int, Path]:
        series_url = str(payload.get("series_url") or "").strip()
        if not series_url:
            raise ValueError("Latest update payload is missing its series URL.")
        _ws, tree = self.ws_mgr.load(series_url, payload.get("series_title"))
        merged, added = self.ws_mgr.merge_latest_payload(tree, payload)
        paths = self.ws_mgr.create_or_update_from_payload(merged)
        self.active_workspace_dir = paths.root
        return merged, added, paths.root

    def clean_active_chapter_content(self, *, on_progress: Callable[[int, int, str], None] | None = None) -> dict[str, int]:
        if self.active_workspace_dir is None:
            raise RuntimeError("No workspace is currently open.")
        project = EpubWorkspaceProject(self.active_workspace_dir)
        return project.repair_comment_metadata(on_progress=on_progress)

    def repair_active_workspace(self, *, on_progress: Callable[[int, int, str], None] | None = None) -> dict:
        """Repair known markup damage, then identify cached chapters needing a fresh download."""
        if self.active_workspace_dir is None:
            raise RuntimeError("No workspace is currently open.")
        project = EpubWorkspaceProject(self.active_workspace_dir)
        repair = project.repair_comment_metadata(on_progress=on_progress)
        if on_progress is not None:
            on_progress(0, 0, "Checking cached chapters for paywall artifacts and incomplete downloads...")
        download_check = project.scan_downloaded_chapters(on_progress=on_progress)
        return {"comment_metadata": repair, "download_check": download_check}

    def load_saved_selection(self, payload: dict) -> dict:
        series_url = str(payload.get("series_url") or "").strip()
        if not series_url:
            return {"selected_volume_indices": [], "selected_chapter_urls": []}
        ws, _ = self.ws_mgr.load(series_url, payload.get("series_title"))
        return ws.get("selection") or {"selected_volume_indices": [], "selected_chapter_urls": []}

    def update_selection(self, payload: dict, selection_state: dict) -> None:
        series_url = str(payload.get("series_url") or "").strip()
        series_title = str(payload.get("series_title") or "Unknown Series").strip()
        if not series_url:
            return
        self.ws_mgr.update_selection(
            series_url=series_url,
            series_title=series_title,
            selected_volume_indices=list(selection_state.get("selected_volume_indices", []) or []),
            selected_chapter_urls=list(selection_state.get("selected_chapter_urls", []) or []),
        )

    def scan_active_workspace_downloads(
        self,
        *,
        min_chars: int = 500,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        if self.active_workspace_dir is None:
            raise RuntimeError("No workspace is currently open.")
        project = EpubWorkspaceProject(self.active_workspace_dir)
        return project.scan_downloaded_chapters(min_chars=min_chars, on_progress=on_progress)

    def active_downloaded_urls(self) -> set[str]:
        if self.active_workspace_dir is None:
            return set()
        return EpubWorkspaceProject(self.active_workspace_dir).downloaded_chapter_urls()
