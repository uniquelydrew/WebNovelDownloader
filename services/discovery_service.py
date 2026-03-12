from __future__ import annotations

from copy import deepcopy
from typing import Any


class DiscoveryService:
    """Compatibility wrapper around the active Playwright discovery implementation.

    Older call sites expected a parsing-oriented service. The repository has since
    standardized on `PlaywrightDiscoveryService.load()` returning a normalized
    payload dict. This wrapper preserves the public entrypoint while enforcing a
    stable shape for downstream consumers.
    """

    def __init__(self, browser: Any | None = None):
        if browser is None:
            from services.playwright_discovery import PlaywrightDiscoveryService

            browser = PlaywrightDiscoveryService()
        self.browser = browser

    def load_series_from_url(self, url: str) -> dict[str, Any]:
        payload = self.browser.load(url)
        return self.normalize_payload(payload, fallback_url=url)

    @staticmethod
    def normalize_payload(payload: Any, *, fallback_url: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError(f"Discovery payload must be a dict, got {type(payload).__name__}")

        normalized = deepcopy(payload)
        normalized["series_url"] = str(normalized.get("series_url") or fallback_url or "").strip()
        normalized["series_title"] = str(normalized.get("series_title") or "Unknown Series").strip() or "Unknown Series"

        out_volumes: list[dict[str, Any]] = []
        for volume_index, volume in enumerate(normalized.get("volumes") or [], start=1):
            if not isinstance(volume, dict):
                continue
            volume_title = str(volume.get("title") or f"Volume {volume_index}").strip() or f"Volume {volume_index}"
            out_chapters: list[dict[str, Any]] = []
            for chapter_index, chapter in enumerate(volume.get("chapters") or [], start=1):
                if not isinstance(chapter, dict):
                    continue
                title = str(chapter.get("title") or f"Chapter {chapter_index}").strip() or f"Chapter {chapter_index}"
                chapter_url = str(chapter.get("url") or "").strip()
                out_chapters.append({"title": title, "url": chapter_url})
            out_volumes.append({"title": volume_title, "chapters": out_chapters})

        normalized["volumes"] = out_volumes
        return normalized