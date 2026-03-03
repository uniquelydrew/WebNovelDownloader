from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Iterator

from lxml import html
from playwright.sync_api import sync_playwright

from clean.cleaner import Cleaner
from extract.content import find_content_container, extract_text
from models.chapter import Chapter
from utils.rotating_logger import LineRotatingJSONLogger


class _LxmlResponse:
    def __init__(self, root):
        self._root = root

    def xpath(self, query: str):
        return self._root.xpath(query)


class PlaywrightChapterCrawler:
    """Fetch chapter pages inside the same authenticated browser session used for discovery.

    Default behavior attaches to an existing Chrome instance via CDP at http://127.0.0.1:9222.
    This preserves your current authenticated-browser workflow.
    """

    UNAUTHORIZED_MARKERS = (
        "Log in to continue your adventure",
        "Unlock free chapters every day",
        "Other benefits you will get",
    )

    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.log_root = self.project_root / "log"
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.logger = LineRotatingJSONLogger(str(self.log_root / "chapter_fetch.log"))

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure(self) -> None:
        if self._page is not None:
            return

        self._pw = sync_playwright().start()

        mode = (os.getenv("WNS_CHAPTER_MODE") or "cdp").strip().lower()
        if mode not in ("cdp",):
            raise RuntimeError(f"Unsupported WNS_CHAPTER_MODE={mode!r}. Only 'cdp' is supported in this build.")

        self._browser = self._pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        if not self._browser.contexts:
            raise RuntimeError("No Chrome contexts available on CDP connection.")
        self._context = self._browser.contexts[0]
        self._page = self._context.new_page()

        self.logger.log("chapter_fetch", "cdp_connected", {"contexts": len(self._browser.contexts)})

    def close(self) -> None:
        try:
            if self._page is not None:
                self._page.close()
        finally:
            self._page = None
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            self._browser = None
        try:
            if self._pw is not None:
                self._pw.stop()
        finally:
            self._pw = None

    def fetch_chapters(self, items: Iterable[dict], cleaner: Cleaner) -> Iterator[Chapter]:
        self._ensure()

        max_errors = int(os.getenv("WNS_MAX_CHAPTER_ERRORS", "5"))
        error_count = 0
        total_processed = 0

        for item in items:
            url = str(item["url"])
            vol_index = int(item["volume_index"])
            vol_title = str(item["volume_title"])
            ch_index = int(item["chapter_index"])
            ch_title = str(item["chapter_title"]).strip() or f"Chapter {ch_index}"

            self.logger.log("chapter_fetch", "goto", {"url": url, "volume_index": vol_index, "chapter_index": ch_index})

            try:
                self._page.goto(url, timeout=60000)
                self._page.wait_for_load_state("domcontentloaded", timeout=60000)
                time.sleep(0.75)

                # Extract HTML and text signals
                html_text = self._page.content()
                body_text = ""
                try:
                    body_text = self._page.inner_text("body")
                except Exception:
                    body_text = html_text

                # Fast-fail if unauthorized / preview gating
                for marker in self.UNAUTHORIZED_MARKERS:
                    if marker in body_text:
                        self.logger.log("chapter_fetch", "preview_detected_initial", {
                            "url": url,
                            "marker": marker,
                        })

                        # 5-second hydration grace window
                        preview_still_present = True
                        start_time = time.time()

                        while time.time() - start_time < 5:
                            time.sleep(0.5)

                            try:
                                body_retry = self._page.inner_text("body")
                            except Exception:
                                body_retry = ""

                            if not any(m in body_retry for m in self.UNAUTHORIZED_MARKERS):
                                preview_still_present = False
                                break

                        if preview_still_present:
                            self.logger.log("chapter_fetch", "preview_persisted_after_grace", {
                                "url": url
                            })
                            raise RuntimeError(f"Unauthorized preview persisted at {url}")
                        else:
                            self.logger.log("chapter_fetch", "preview_resolved_after_grace", {
                                "url": url
                            })
                            break

                # Parse DOM and remove blockquotes aggressively
                root = html.fromstring(html_text)
                removed_bq = 0
                for node in root.xpath("//blockquote"):
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                        removed_bq += 1
                if removed_bq:
                    self.logger.log("chapter_fetch", "removed_blockquotes", {"url": url, "count": removed_bq})

                resp = _LxmlResponse(root)
                container = find_content_container(resp)
                if container is None:
                    self.logger.log("chapter_fetch", "missing_container", {"url": url})
                    raise RuntimeError(f"Missing content container for {url}")

                raw = extract_text(container)
                clean = cleaner.clean(raw)

                # Minimum-length guard
                if len(clean.strip()) < int(os.getenv("WNS_MIN_CHAPTER_CHARS", "500")):
                    self.logger.log("chapter_fetch", "too_short", {"url": url, "chars": len(clean.strip())})
                    raise RuntimeError(f"Chapter content too short (possible preview) at {url}")

                chapter = Chapter(
                    novel_title=str(item.get("series_title") or item.get("novel_title") or "Unknown Series"),
                    volume_index=vol_index,
                    volume_title=vol_title,
                    chapter_index=ch_index,
                    chapter_title=ch_title,
                    chapter_url=url,
                    text=clean,
                )

                total_processed += 1
                yield chapter

            except Exception as e:
                error_count += 1
                self.logger.log("chapter_fetch", "error", {"url": url, "error": str(e)})

                print(json.dumps({
                    "type": "error",
                    "chapter_url": url,
                    "message": str(e),
                }, ensure_ascii=False), flush=True)

                if error_count >= max_errors:
                    self.logger.log("chapter_fetch", "abort_threshold", {
                        "errors": error_count,
                        "max_errors": max_errors,
                    })
                    break
