from __future__ import annotations

import asyncio
import multiprocessing as mp
import sys
from typing import Any


def discovery_entry(
    url: str,
    conn,
    force_refresh: bool = False,
    latest_only: bool = False,
    known_chapter_urls: list[str] | None = None,
    known_volume_titles: list[str] | None = None,
) -> None:
    try:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        from services.playwright_discovery import PlaywrightDiscoveryService

        service = PlaywrightDiscoveryService()
        if force_refresh:
            import os
            os.environ["WNS_TRAVERSAL_FORCE_REFRESH"] = "1"
        payload = service.load(
            url,
            latest_only=latest_only,
            known_chapter_urls=known_chapter_urls,
            known_volume_titles=known_volume_titles,
        )
        conn.send({"ok": True, "payload": payload})
    except Exception as e:
        try:
            conn.send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


class DiscoveryProcess:
    def __init__(
        self,
        url: str,
        *,
        force_refresh: bool = False,
        latest_only: bool = False,
        known_chapter_urls: list[str] | None = None,
        known_volume_titles: list[str] | None = None,
    ):
        self.url = url
        self.force_refresh = force_refresh
        self.latest_only = latest_only
        self.known_chapter_urls = list(known_chapter_urls or [])
        self.known_volume_titles = list(known_volume_titles or [])
        self.parent_conn, self.child_conn = mp.Pipe(duplex=False)
        self.process = mp.Process(
            target=discovery_entry,
            args=(self.url, self.child_conn, self.force_refresh, self.latest_only, self.known_chapter_urls, self.known_volume_titles),
            daemon=True,
        )

    def start(self) -> None:
        self.process.start()
        try:
            self.child_conn.close()
        except Exception:
            pass

    def poll(self) -> bool:
        return self.parent_conn.poll()

    def get_result(self) -> dict[str, Any]:
        return self.parent_conn.recv()

    def join(self, timeout: float | None = None) -> None:
        self.process.join(timeout=timeout)
        if not self.process.is_alive():
            try:
                self.parent_conn.close()
            except Exception:
                pass
