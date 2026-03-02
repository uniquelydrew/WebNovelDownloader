from __future__ import annotations

import asyncio
import multiprocessing as mp
import sys
from typing import Any


def discovery_entry(url: str, conn) -> None:
    try:
        if sys.platform.startswith("win"):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        from services.playwright_discovery import PlaywrightDiscoveryService

        payload = PlaywrightDiscoveryService().load(url)
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
    def __init__(self, url: str):
        self.url = url
        self.parent_conn, self.child_conn = mp.Pipe(duplex=False)
        self.process = mp.Process(
            target=discovery_entry,
            args=(self.url, self.child_conn),
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
