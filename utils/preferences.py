from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from utils.app_paths import preferences_path


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass(slots=True)
class WidgetColorPreference:
    background: str | None = None
    foreground: str | None = None


@dataclass(slots=True)
class AppPreferences:
    workspace_root: str | None = None
    widget_colors_enabled: bool = False
    widget_colors: dict[str, WidgetColorPreference] = field(default_factory=dict)


def _normalize_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if not _HEX_COLOR_RE.match(text):
        return None
    return text


class PreferencesService:
    def __init__(self, path: Path | None = None):
        self.path = path or preferences_path()

    def load(self) -> AppPreferences:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return AppPreferences()

        if not isinstance(raw, dict):
            return AppPreferences()

        workspace_root = raw.get("workspace_root")
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            workspace_root = None
        else:
            workspace_root = str(Path(workspace_root).expanduser())

        colors: dict[str, WidgetColorPreference] = {}
        raw_colors = raw.get("widget_colors")
        if isinstance(raw_colors, dict):
            for key, value in raw_colors.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                background = _normalize_color(value.get("background"))
                foreground = _normalize_color(value.get("foreground"))
                if background or foreground:
                    colors[key] = WidgetColorPreference(background=background, foreground=foreground)

        return AppPreferences(
            workspace_root=workspace_root,
            widget_colors_enabled=bool(raw.get("widget_colors_enabled")),
            widget_colors=colors,
        )

    def save(self, preferences: AppPreferences) -> None:
        payload = asdict(preferences)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def update(self, **changes: Any) -> AppPreferences:
        prefs = self.load()
        for key, value in changes.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        self.save(prefs)
        return prefs
