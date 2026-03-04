from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Iterator

from lxml import html
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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
    This preserves your authenticated-browser workflow.

    Navigation modes:
      - goto: page.goto(target_url) for each chapter
      - pager: when chapters are contiguous, click Next/Previous controls in-page; fallback to goto
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

        # Under CDP, prefer reusing an existing page if present; this tends to be more stable.
        if getattr(self._context, "pages", None) and self._context.pages:
            self._page = self._context.pages[0]
            self.logger.log("chapter_fetch", "page_reuse", {"existing_pages": len(self._context.pages)})
        else:
            self._page = self._context.new_page()
            self.logger.log("chapter_fetch", "page_new", {})

        self.logger.log("chapter_fetch", "cdp_connected", {"contexts": len(self._browser.contexts)})

    def close(self) -> None:
        try:
            if self._page is not None:
                # If this page was an existing tab under CDP, closing it may be undesirable.
                # Respect env flag WNS_CLOSE_PAGE=1 to close; otherwise keep it open.
                if os.getenv("WNS_CLOSE_PAGE") == "1":
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

        nav_mode = (os.getenv("WNS_NAV_MODE") or "pager").strip().lower()
        if nav_mode not in ("pager", "goto"):
            nav_mode = "pager"

        max_errors = int(os.getenv("WNS_MAX_CHAPTER_ERRORS", "5"))
        error_count = 0

        planned = list(items)
        planned.sort(key=lambda it: (int(it.get("volume_index") or 0), int(it.get("chapter_index") or 0)))

        prev = None

        for item in planned:
            url = str(item["url"]).strip()
            vol_index = int(item["volume_index"])
            vol_title = str(item["volume_title"])
            ch_index = int(item["chapter_index"])
            ch_title = str(item["chapter_title"]).strip() or f"Chapter {ch_index}"

            if not url:
                continue

            try:
                if (
                    nav_mode == "pager"
                    and prev is not None
                    and int(prev.get("volume_index") or 0) == vol_index
                    and int(prev.get("chapter_index") or 0) + 1 == ch_index
                ):
                    ok = self._try_nav_next(expected_url=url)
                    if not ok:
                        self._goto(url)
                else:
                    self._goto(url)

                html_text = self._page.content()
                body_text = ""
                try:
                    body_text = self._page.inner_text("body")
                except Exception:
                    body_text = html_text

                self._guard_preview(url=url, body_text=body_text)

                root = html.fromstring(html_text)

                # Remove blockquotes aggressively (footnotes / asides tend to live here)
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

                self.logger.log(
                    "chapter_fetch",
                    "chapter_ok",
                    {
                        "url": url,
                        "volume_index": vol_index,
                        "chapter_index": ch_index,
                        "nav_mode": nav_mode,
                    },
                )

                prev = item
                yield chapter

            except Exception as e:
                error_count += 1
                self.logger.log("chapter_fetch", "error", {"url": url, "error": str(e)})

                print(
                    json.dumps(
                        {
                            "type": "error",
                            "chapter_url": url,
                            "message": str(e),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

                if error_count >= max_errors:
                    self.logger.log(
                        "chapter_fetch",
                        "abort_threshold",
                        {
                            "errors": error_count,
                            "max_errors": max_errors,
                        },
                    )
                    break

    def _goto(self, url: str) -> None:
        self.logger.log("chapter_fetch", "goto", {"url": url})
        self._page.goto(url, timeout=60000)
        self._page.wait_for_load_state("domcontentloaded", timeout=60000)
        time.sleep(float(os.getenv("WNS_POST_GOTO_SLEEP", "0.75")))

    def _guard_preview(self, url: str, body_text: str) -> None:
        for marker in self.UNAUTHORIZED_MARKERS:
            if marker in body_text:
                self.logger.log("chapter_fetch", "preview_detected_initial", {"url": url, "marker": marker})

                # Hydration grace window
                preview_still_present = True
                start_time = time.time()

                while time.time() - start_time < float(os.getenv("WNS_PREVIEW_GRACE_SECONDS", "5")):
                    time.sleep(0.5)
                    try:
                        body_retry = self._page.inner_text("body")
                    except Exception:
                        body_retry = ""

                    if not any(m in body_retry for m in self.UNAUTHORIZED_MARKERS):
                        preview_still_present = False
                        break

                if preview_still_present:
                    self.logger.log("chapter_fetch", "preview_persisted_after_grace", {"url": url})
                    raise RuntimeError(f"Unauthorized preview persisted at {url}")

                self.logger.log("chapter_fetch", "preview_resolved_after_grace", {"url": url})
                return

    def _try_nav_next(self, expected_url: str) -> bool:
        """Attempt to advance using in-page Next controls.

        Returns True if navigation appears to land on expected_url.
        """
        old_url = (self._page.url or "").strip()
        if not old_url:
            return False

        locator = self._find_next_control()
        if locator is None:
            self.logger.log("chapter_fetch", "pager_next_missing", {"expected_url": expected_url})
            return False

        self.logger.log(
            "chapter_fetch",
            "pager_next_attempt",
            {"from": old_url, "expected_url": expected_url},
        )

        try:
            locator.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        try:
            locator.click(timeout=8000)
        except Exception as e:
            self.logger.log("chapter_fetch", "pager_next_click_failed", {"error": str(e)})
            return False

        try:
            self._page.wait_for_url(lambda u: u != old_url, timeout=15000)
        except PlaywrightTimeoutError:
            # URL may not change (some SPAs update content without URL); fallback to content-based wait.
            try:
                self._page.wait_for_function(
                    """
                    (old) => {
                        try {
                            return window.location.href !== old;
                        } catch (e) {
                            return false;
                        }
                    }
                    """,
                    arg=old_url,
                    timeout=15000,
                )
            except Exception:
                pass

        time.sleep(float(os.getenv("WNS_POST_PAGER_SLEEP", "0.35")))

        cur = (self._page.url or "").strip()
        if cur == expected_url:
            self.logger.log("chapter_fetch", "pager_next_ok", {"url": cur})
            return True

        # Some sites normalize/redirect URLs; accept if the expected URL is a prefix match.
        if expected_url and cur and (cur.rstrip("/") == expected_url.rstrip("/")):
            self.logger.log("chapter_fetch", "pager_next_ok_normalized", {"url": cur, "expected": expected_url})
            return True

        self.logger.log("chapter_fetch", "pager_next_mismatch", {"url": cur, "expected": expected_url})
        return False

    def _find_next_control(self):
        """Heuristic Next control locator.

        Returns a Locator-like object or None.
        """
        candidates = [
            "a[rel='next']",
            "button[rel='next']",
            "a[aria-label*='Next' i]",
            "button[aria-label*='Next' i]",
            "a:has-text('Next')",
            "button:has-text('Next')",
            "a:has-text('›')",
            "button:has-text('›')",
        ]

        for sel in candidates:
            try:
                loc = self._page.locator(sel)
                if loc.count() <= 0:
                    continue

                # Prefer first visible/enabled instance
                for i in range(min(4, loc.count())):
                    cand = loc.nth(i)
                    try:
                        if not cand.is_visible():
                            continue
                    except Exception:
                        pass
                    # Some implementations disable via aria-disabled
                    try:
                        aria_disabled = (cand.get_attribute("aria-disabled") or "").strip().lower()
                        if aria_disabled in ("true", "1"):
                            continue
                    except Exception:
                        pass

                    return cand
            except Exception:
                continue

        return None
