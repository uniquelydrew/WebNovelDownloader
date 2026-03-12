from __future__ import annotations

from pathlib import Path

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
