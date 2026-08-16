from __future__ import annotations

import json
import os
import sys
import time
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from utils.app_paths import cache_root, configure_playwright_env, log_root
from utils.browser_runtime import cdp_endpoint, ensure_managed_browser
from utils.rotating_logger import LineRotatingJSONLogger
from workspaces.manager import WorkspaceManager


class PlaywrightDiscoveryService:
    def __init__(self):
        configure_playwright_env()
        self.log_root = log_root()
        self.logger = LineRotatingJSONLogger(str(self.log_root / "discovery.log"))
        self.snapshot_dir = self.log_root / "payload_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.cache_root = cache_root() / "traversal"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = int(os.getenv("WNS_TRAVERSAL_CACHE_TTL", 60 * 60 * 24))
        self._collected_in_oldest_order = False

    def load(
        self,
        url: str,
        *,
        latest_only: bool = False,
        known_chapter_urls: list[str] | None = None,
        known_volume_titles: list[str] | None = None,
    ) -> dict:
        self._collected_in_oldest_order = False
        force_refresh = os.getenv("WNS_TRAVERSAL_FORCE_REFRESH") == "1"
        cache_disabled = os.getenv("WNS_TRAVERSAL_CACHE_DISABLE") == "1"
        known_chapter_urls = list(known_chapter_urls or [])
        known_volume_titles = list(known_volume_titles or [])

        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = self.cache_root / f"{cache_key}.json"
        if not latest_only and not cache_disabled and not force_refresh and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_ttl_seconds:
                return json.loads(cache_path.read_text(encoding="utf-8"))

        run_dir = self._make_run_dir()
        console_path = run_dir / "console.jsonl"

        def on_console(msg):
            try:
                rec = {"ts": time.time(), "type": msg.type, "text": msg.text}
                if not console_path.exists():
                    console_path.write_text("", encoding="utf-8")
                with console_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass

        launch_result = ensure_managed_browser(open_url=url)
        self.logger.log(
            "discovery",
            "cdp_ready",
            {
                "url": url,
                "run_dir": str(run_dir),
                "endpoint": launch_result.endpoint,
                "launched": launch_result.launched,
                "already_running": launch_result.already_running,
                "browser_executable": launch_result.browser_executable,
            },
        )

        ws: WorkspaceManager | None = None
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_endpoint())
            if not browser.contexts:
                self._write_probe(run_dir, {"fatal": "no_cdp_contexts"})
                raise RuntimeError("No browser contexts available on CDP connection.")

            context = browser.contexts[0]
            page = context.new_page()
            page.on("console", on_console)

            try:
                page.goto(url, timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                self._ensure_chapters_tab(page)
                if not latest_only:
                    self._collected_in_oldest_order = self._ensure_oldest_first(page)

                if not latest_only:
                    try:
                        ws = WorkspaceManager(series_url=url, series_title=None)
                    except Exception as e:
                        ws = None
                        self.logger.log("discovery", "workspace_init_failed", {"error": f"{type(e).__name__}: {e}"})

                self._dump_page(run_dir, page, phase="after_goto")
                time.sleep(2.0)
                self._dump_page(run_dir, page, phase="after_hydration_wait")
                if latest_only:
                    payload = self._extract_latest_payload(
                        page,
                        url,
                        run_dir=run_dir,
                        known_chapter_urls=known_chapter_urls,
                        known_volume_titles=known_volume_titles,
                    )
                else:
                    payload = self._extract_payload(page, url, run_dir=run_dir, workspace=ws)

                if ws is not None:
                    try:
                        ws.update_series_title(payload.get("series_title") or "Unknown Series")
                        ws.mark_completed()
                    except Exception:
                        pass

                self._persist_payload_snapshot(payload)
                if not latest_only:
                    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                (run_dir / "payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                self.logger.log(
                    "discovery",
                    "payload_complete",
                    {
                        "debug_run_dir": str(run_dir),
                        "volumes": len(payload.get("volumes", [])),
                        "chapters": sum(len(v.get("chapters", [])) for v in payload.get("volumes", [])),
                    },
                )
                self.logger.log("discovery", "payload_full", payload)
                return payload
            except Exception as e:
                try:
                    self._dump_page(run_dir, page, phase="exception")
                except Exception:
                    pass
                if ws is not None:
                    try:
                        ws.mark_error(f"{type(e).__name__}: {e}")
                    except Exception:
                        pass
                self.logger.log("discovery", "exception", {"error": f"{type(e).__name__}: {e}", "debug_run_dir": str(run_dir)})
                raise
            finally:
                try:
                    page.close()
                except Exception:
                    pass

    def _ensure_oldest_first(self, page) -> bool:
        toolbar = page.locator("div.flex.flex-1.items-end.justify-end").first
        newest_button = toolbar.locator("button").filter(has_text="Newest").first
        oldest_button = toolbar.locator("button").filter(has_text="Oldest").first
        chapter_links = page.locator("a[href*='-chapter-'], a[href*='/chapter/']")

        try:
            oldest_count = oldest_button.count()
            newest_count = newest_button.count()
            if oldest_count > 0 and newest_count == 0:
                self.logger.log("discovery", "sort_order_set", {"selector": "button:has-text('Oldest')", "changed": False})
                return True
        except Exception:
            pass

        try:
            if newest_button.count() > 0:
                before_href = None
                try:
                    if chapter_links.count() > 0:
                        before_href = chapter_links.first.get_attribute("href")
                except Exception:
                    pass

                newest_button.scroll_into_view_if_needed(timeout=3000)
                newest_button.click(timeout=5000)

                oldest_option = page.locator(
                    "div.absolute.top-\\[calc\\(100\\%\\+8px\\)\\].right-0.z-10.w-\\[160px\\] div"
                ).filter(has_text="Oldest").first
                oldest_option.wait_for(state="visible", timeout=5000)
                oldest_option.click(timeout=5000)

                changed = False
                try:
                    page.wait_for_function(
                        """
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button'));
                            return buttons.some((button) => (button.textContent || '').includes('Oldest'));
                        }
                        """,
                        timeout=5000,
                    )
                    changed = True
                except Exception:
                    if before_href:
                        try:
                            page.wait_for_function(
                                """
                                (previousHref) => {
                                    const firstLink = document.querySelector("a[href*='/chapter/']");
                                    return !!firstLink && firstLink.getAttribute('href') !== previousHref;
                                }
                                """,
                                arg=before_href,
                                timeout=5000,
                            )
                            changed = True
                        except Exception:
                            pass

                page.wait_for_timeout(750)

                self.logger.log(
                    "discovery",
                    "sort_order_set",
                    {
                        "selector": "button:has-text('Newest') -> div:has-text('Oldest')",
                        "changed": changed,
                    },
                )
                if changed:
                    return True
        except Exception as e:
            self.logger.log("discovery", "sort_order_click_failed", {"error": f"{type(e).__name__}: {e}"})

        self.logger.log("discovery", "sort_order_set", {"selector": None, "fallback": "reverse_collected_order"})
        return False

    def _ensure_chapters_tab(self, page) -> None:
        try:
            selected_tab = page.locator("button[role='tab'][aria-selected='true']").first
            if selected_tab.count() > 0:
                selected_text = (selected_tab.text_content() or "").strip().lower()
                if "chapters" in selected_text:
                    self.logger.log("discovery", "chapters_tab", {"changed": False})
                    return
        except Exception:
            pass

        try:
            chapters_tab = page.locator("button[role='tab']").filter(has_text="Chapters").first
            chapters_tab.wait_for(state="visible", timeout=10000)
            chapters_tab.scroll_into_view_if_needed(timeout=3000)
            chapters_tab.click(timeout=5000)
            page.wait_for_function(
                """
                () => {
                    const selected = document.querySelector("button[role='tab'][aria-selected='true']");
                    return !!selected && (selected.textContent || '').includes('Chapters');
                }
                """,
                timeout=10000,
            )
            page.wait_for_timeout(750)
            self.logger.log("discovery", "chapters_tab", {"changed": True})
        except Exception as e:
            self.logger.log("discovery", "chapters_tab_failed", {"error": f"{type(e).__name__}: {e}"})

    def _extract_payload(self, page, url: str, run_dir, workspace: WorkspaceManager | None) -> dict:
        series_title = (page.title() or "").strip() or "Unknown Series"
        if workspace is not None:
            try:
                workspace.update_series_title(series_title)
            except Exception:
                pass

        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.wuxiaworld.com"
        volumes: list[dict] = []
        accordions = page.locator(".MuiAccordion-root")
        accordion_count = accordions.count()
        self.logger.log(
            "discovery",
            "dom_metrics",
            {
                "accordion_count": accordion_count,
                "role_button_aria_expanded": page.locator("[role='button'][aria-expanded]").count(),
                "anchor_group_count": page.locator("a.group").count(),
                "page_url": page.url,
            },
        )

        if accordion_count > 0:
            for i in range(accordion_count):
                accordion = accordions.nth(i)
                # Wuxiaworld currently renders AccordionSummary as a native button
                # without role="button".  Keep the role selector for older markup.
                summary = accordion.locator("button.MuiAccordionSummary-root, [role='button']")
                title_el = summary.locator("span.font-set-sb18")
                title = f"Volume {i + 1}"
                try:
                    if title_el.count() > 0:
                        title = (title_el.text_content() or "").strip() or title
                    elif summary.count() > 0:
                        title = (summary.text_content() or "").strip() or title
                except Exception:
                    pass
                try:
                    expanded = summary.get_attribute("aria-expanded")
                except Exception:
                    expanded = None
                if expanded != "true":
                    try:
                        summary.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    try:
                        summary.click(timeout=5000)
                    except Exception:
                        pass
                    time.sleep(0.6)

                details = accordion.locator(".MuiAccordionDetails-root")
                if not self._wait_for_volume_chapters(details):
                    self.logger.log("discovery", "volume_wait_timeout", {"index": i, "title": title, "debug_run_dir": str(run_dir)})

                chapters = self._normalize_chapter_order(self._collect_chapters_from_details(details, base=base))
                print(f"[DISCOVERY] Volume {i + 1}: {title} ({len(chapters)} chapters)", file=sys.stdout, flush=True)
                self.logger.log("discovery", "volume_collected", {"index": i, "title": title, "chapter_count": len(chapters)})

                if chapters:
                    volumes.append({"title": title, "chapters": chapters})
                    if workspace is not None:
                        try:
                            workspace.append_volume(title=title, chapters=chapters)
                        except Exception as e:
                            self.logger.log("discovery", "workspace_volume_write_failed", {"index": i, "title": title, "error": f"{type(e).__name__}: {e}"})

            try:
                (run_dir / "post_volume_expansion_page.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            return {"debug_run_dir": str(run_dir), "series_title": series_title, "series_url": url, "volumes": volumes}

        chapters = self._normalize_chapter_order(self._collect_flat_chapters(page, base=base, series_url=url))
        print(f"[DISCOVERY] Flat mode: {len(chapters)} chapters", file=sys.stdout, flush=True)
        if chapters:
            volumes.append({"title": "Volume 1", "chapters": chapters})
            if workspace is not None:
                try:
                    workspace.append_volume(title="Volume 1", chapters=chapters)
                except Exception as e:
                    self.logger.log("discovery", "workspace_volume_write_failed", {"index": 0, "title": "Volume 1", "error": f"{type(e).__name__}: {e}"})

        return {"debug_run_dir": str(run_dir), "series_title": series_title, "series_url": url, "volumes": volumes}

    def _extract_latest_payload(self, page, url: str, run_dir, known_chapter_urls: list[str], known_volume_titles: list[str]) -> dict:
        """Collect only the newest volume frontier until a known chapter is reached."""
        series_title = (page.title() or "").strip() or "Unknown Series"
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.wuxiaworld.com"
        known_urls = set(known_chapter_urls)
        volumes: list[dict] = []
        accordions = page.locator(".MuiAccordion-root")
        # Labels can change while Wuxiaworld hydrates the chapter tab, and one
        # logical volume can be split across adjacent accordions.  Use chapter
        # URL overlap as the frontier signal instead of the displayed title.
        indices = range(min(4, accordions.count()))
        known_blocks = 0

        for i in indices:
            accordion = accordions.nth(i)
            summary = accordion.locator("button.MuiAccordionSummary-root, [role='button']")
            title_el = summary.locator("span.font-set-sb18")
            title = f"Volume {i + 1}"
            try:
                if title_el.count() > 0:
                    title = (title_el.text_content() or "").strip() or title
                elif summary.count() > 0:
                    title = (summary.text_content() or "").strip() or title
            except Exception:
                pass

            try:
                if summary.get_attribute("aria-expanded") != "true":
                    summary.scroll_into_view_if_needed(timeout=5000)
                    summary.click(timeout=5000)
            except Exception:
                pass

            details = accordion.locator(".MuiAccordionDetails-root")
            if not self._wait_for_volume_chapters(details):
                self.logger.log("discovery", "latest_volume_wait_timeout", {"index": i, "title": title})

            chapters = self._normalize_chapter_order(self._collect_chapters_from_details(details, base=base))
            if not chapters:
                continue
            volumes.append({"title": title, "chapters": chapters})

            has_known_chapter = any(chapter["url"] in known_urls for chapter in chapters)
            if has_known_chapter:
                known_blocks += 1
            self.logger.log(
                "discovery",
                "latest_volume_collected",
                {"index": i, "title": title, "chapter_count": len(chapters), "known_blocks": known_blocks, "has_known_chapter": has_known_chapter},
            )
            if known_blocks >= 2:
                break

        return {
            "debug_run_dir": str(run_dir),
            "series_title": series_title,
            "series_url": url,
            "volumes": volumes,
            "latest_only": True,
        }

    def _normalize_chapter_order(self, chapters: list[dict]) -> list[dict]:
        if len(chapters) <= 1:
            return chapters
        if self._collected_in_oldest_order:
            return chapters
        return list(reversed(chapters))

    @staticmethod
    def _wait_for_volume_chapters(details) -> bool:
        try:
            details.locator("a.group").first.wait_for(state="attached", timeout=15000)
            return True
        except Exception:
            return False

    def _collect_chapters_from_details(self, details, base: str) -> list[dict]:
        anchors = details.locator("a.group")
        items: list[dict] = []
        seen = set()
        try:
            records = anchors.evaluate_all(
                """
                (anchors) => anchors.map((anchor) => ({
                    href: anchor.getAttribute('href') || '',
                    title: (anchor.querySelector('span')?.textContent || anchor.textContent || '').trim(),
                }))
                """
            )
        except Exception:
            records = []
        for record in records:
            href = str(record.get("href") or "")
            if not href:
                continue
            abs_href = urljoin(base, href)
            title = " ".join(str(record.get("title") or "").split()) or abs_href
            if abs_href in seen:
                continue
            seen.add(abs_href)
            items.append({"title": title, "url": abs_href})
        return items

    def _collect_flat_chapters(self, page, base: str, series_url: str) -> list[dict]:
        parsed = urlparse(series_url)
        parts = [p for p in parsed.path.split("/") if p]
        series_slug = parts[-1] if parts else ""
        base_prefix = f"/novel/{series_slug}" if series_slug else ""
        anchors = page.locator("a[href*='/novel/']")
        prev = -1
        stable = 0
        for _ in range(160):
            cur = anchors.count()
            stable = stable + 1 if cur == prev else 0
            prev = cur
            if cur > 0 and stable >= 6:
                break
            try:
                page.mouse.wheel(0, 2000)
            except Exception:
                pass
            time.sleep(0.15)

        items: list[dict] = []
        seen = set()
        for i in range(anchors.count()):
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()
            if not href:
                continue
            if base_prefix:
                if href.startswith("/") and not href.startswith(base_prefix + "/"):
                    continue
                if href == base_prefix:
                    continue
            abs_href = urljoin(base, href)
            if not text:
                text = abs_href
            if abs_href in seen:
                continue
            seen.add(abs_href)
            items.append({"title": text, "url": abs_href})
        return items

    def _persist_payload_snapshot(self, payload: dict) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        snapshot_file = self.snapshot_dir / f"payload_{timestamp}.json"
        snapshot_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _make_run_dir(self):
        root = self.log_root / "debug_runs"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        run_dir = root / f"{stamp}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _dump_page(self, run_dir, page, phase: str) -> None:
        try:
            page.screenshot(path=str(run_dir / f"{phase}_screenshot.png"), full_page=True)
        except Exception:
            pass
        try:
            html = page.content()
            (run_dir / f"{phase}_page.html").write_text(html, encoding="utf-8")
        except Exception:
            pass

        probe = self._probe_dom(page)
        probe["phase"] = phase
        probe["ts"] = time.time()
        probe["page_url"] = page.url
        try:
            probe["page_title"] = (page.title() or "").strip()
        except Exception:
            probe["page_title"] = ""
        (run_dir / f"{phase}_probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")

    def _probe_dom(self, page) -> dict:
        selectors = {
            "aria_expanded_any": "[aria-expanded]",
            "role_button_aria_expanded": "[role='button'][aria-expanded]",
            "button_aria_expanded": "button[aria-expanded]",
            "aria_controls": "[aria-controls]",
            "aria_expanded_and_controls": "[aria-expanded][aria-controls]",
            "chapter_links_any": "a[href*='/chapter/']",
            "novel_links_any": "a[href*='/novel/']",
            "accordion_like": "[role='button'][aria-controls]",
            "mui_accordion_root": ".MuiAccordion-root",
            "mui_accordion_details": ".MuiAccordionDetails-root",
            "anchor_group": "a.group",
        }
        out = {"ready_state": None, "selectors": {}, "samples": {}, "chapter_link_samples": []}
        try:
            out["ready_state"] = page.evaluate("() => document.readyState")
        except Exception:
            pass
        for k, sel in selectors.items():
            try:
                out["selectors"][k] = page.locator(sel).count()
            except Exception:
                out["selectors"][k] = None
        for k, sel in selectors.items():
            try:
                loc = page.locator(sel)
                samples = []
                for i in range(min(3, loc.count())):
                    html = loc.nth(i).evaluate("el => el.outerHTML")
                    samples.append(html[:4000])
                out["samples"][k] = samples
            except Exception:
                out["samples"][k] = []
        try:
            loc = page.locator("a[href]")
            got = 0
            for i in range(min(2000, loc.count())):
                href = loc.nth(i).get_attribute("href") or ""
                if "/chapter/" in href:
                    text = (loc.nth(i).inner_text() or "").strip()
                    out["chapter_link_samples"].append({"href": href, "text": text[:200]})
                    got += 1
                    if got >= 50:
                        break
        except Exception:
            pass
        return out

    def _write_probe(self, run_dir, payload: dict) -> None:
        try:
            (run_dir / "fatal_probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
