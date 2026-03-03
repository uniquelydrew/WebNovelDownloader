from __future__ import annotations

import json
import os
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from utils.rotating_logger import LineRotatingJSONLogger


class PlaywrightDiscoveryService:
    def __init__(self):
        # Project root is parent of /services
        self.project_root = Path(__file__).resolve().parents[1]
        self.log_root = self.project_root / "log"
        self.log_root.mkdir(parents=True, exist_ok=True)

        self.logger = LineRotatingJSONLogger(str(self.log_root / "discovery.log"))

        self.snapshot_dir = self.log_root / "payload_snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self.cache_root = self.project_root / "cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = int(
            os.getenv("WNS_TRAVERSAL_CACHE_TTL", 60 * 60 * 24)
        )

        # Traversal cache (volume tree only)
        self.cache_root = self.project_root / "cache" / "traversal"
        self.cache_root.mkdir(parents=True, exist_ok=True)

        self.cache_ttl_seconds = int(
            os.getenv("WNS_TRAVERSAL_CACHE_TTL", 60 * 60 * 24)
        )

    def load(self, url: str) -> dict:
        force_refresh = os.getenv("WNS_TRAVERSAL_FORCE_REFRESH") == "1"
        cache_disabled = os.getenv("WNS_TRAVERSAL_CACHE_DISABLE") == "1"

        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_path = self.cache_root / f"{cache_key}.json"

        if not cache_disabled and not force_refresh and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_ttl_seconds:
                return json.loads(cache_path.read_text(encoding="utf-8"))

        run_dir = self._make_run_dir()
        console_path = run_dir / "console.jsonl"

        def on_console(msg):
            # Best-effort capture of browser console
            try:
                rec = {
                    "ts": time.time(),
                    "type": msg.type,
                    "text": msg.text,
                }
                if not console_path.exists():
                    console_path.write_text("", encoding="utf-8")
                with console_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                # Console capture must never break discovery
                pass

        self.logger.log("discovery", "cdp_connect_attempt", {"url": url, "run_dir": str(run_dir)})

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            if not browser.contexts:
                self._write_probe(run_dir, {"fatal": "no_cdp_contexts"})
                raise RuntimeError("No Chrome contexts available on CDP connection.")

            context = browser.contexts[0]
            page = context.new_page()
            page.on("console", on_console)

            try:
                page.goto(url, timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=60000)

                self._dump_page(run_dir, page, phase="after_goto")

                time.sleep(2.0)
                self._dump_page(run_dir, page, phase="after_hydration_wait")

                payload = self._extract_payload(page, url, run_dir=run_dir)

                # Persist payload for offline inspection
                self._persist_payload_snapshot(payload)
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
                self.logger.log(
                    "discovery",
                    "exception",
                    {"error": f"{type(e).__name__}: {e}", "debug_run_dir": str(run_dir)},
                )
                raise
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    def _extract_payload(self, page, url: str, run_dir: Path) -> dict:
        series_title = (page.title() or "").strip() or "Unknown Series"

        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.wuxiaworld.com"

        volumes: list[dict] = []

        # Prefer direct accordion traversal (WuxiaWorld index uses MUI accordion for volumes)
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
                summary = accordion.locator("[role='button']")
                title_el = summary.locator("span.font-set-sb18")
                title = (title_el.inner_text() or "").strip() or f"Volume {i + 1}"

                # Expand if needed
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
                    # Let MUI animation/lazy mount complete
                    time.sleep(0.6)

                details = accordion.locator(".MuiAccordionDetails-root")

                # Wait until chapters mount inside this accordion
                try:
                    page.wait_for_function(
                        """
                        (el) => {
                            if (!el) return false;
                            return el.querySelectorAll("a.group").length > 0;
                        }
                        """,
                        arg=details,
                        timeout=15000,
                    )
                except Exception:
                    # Snapshot per-volume failure
                    self.logger.log(
                        "discovery",
                        "volume_wait_timeout",
                        {"index": i, "title": title, "debug_run_dir": str(run_dir)},
                    )

                chapters = self._collect_chapters_from_details(details, base=base)

                # Console trace per volume (requested)
                print(f"[DISCOVERY] Volume {i + 1}: {title} ({len(chapters)} chapters)", file=sys.stdout, flush=True)

                self.logger.log(
                    "discovery",
                    "volume_collected",
                    {"index": i, "title": title, "chapter_count": len(chapters)},
                )

                if chapters:
                    volumes.append({"title": title, "chapters": chapters})

            # Dump DOM after expansions for offline inspection
            try:
                (run_dir / "post_volume_expansion_page.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass

            return {
                "debug_run_dir": str(run_dir),
                "series_title": series_title,
                "series_url": url,
                "volumes": volumes,
            }

        # Fallback: no accordion; collect flat chapter anchors (still structured as one synthetic volume)
        chapters = self._collect_flat_chapters(page, base=base, series_url=url)
        print(f"[DISCOVERY] Flat mode: {len(chapters)} chapters", file=sys.stdout, flush=True)
        if chapters:
            volumes.append({"title": "Volume 1", "chapters": chapters})

        return {
            "debug_run_dir": str(run_dir),
            "series_title": series_title,
            "series_url": url,
            "volumes": volumes,
        }

    def _collect_chapters_from_details(self, details, base: str) -> list[dict]:
        anchors = details.locator("a.group")
        n = anchors.count()

        items: list[dict] = []
        seen = set()

        for i in range(n):
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            if not href:
                continue

            abs_href = urljoin(base, href)

            # Prefer the chapter title span; fallback to anchor inner_text
            title_span = a.locator("span").first
            try:
                title = (title_span.inner_text() or "").strip()
            except Exception:
                title = ""

            if not title:
                try:
                    title = (a.inner_text() or "").strip()
                except Exception:
                    title = abs_href

            key = abs_href
            if key in seen:
                continue
            seen.add(key)

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
            if cur == prev:
                stable += 1
            else:
                stable = 0
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
        n = anchors.count()

        for i in range(n):
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

    def _make_run_dir(self) -> Path:
        root = self.log_root / "debug_runs"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        run_dir = root / f"{stamp}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _dump_page(self, run_dir: Path, page, phase: str) -> None:
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

        out = {
            "ready_state": None,
            "selectors": {},
            "samples": {},
            "chapter_link_samples": [],
        }

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
                n = min(3, loc.count())
                samples = []
                for i in range(n):
                    html = loc.nth(i).evaluate("el => el.outerHTML")
                    samples.append(html[:4000])
                out["samples"][k] = samples
            except Exception:
                out["samples"][k] = []

        try:
            loc = page.locator("a[href]")
            n = min(2000, loc.count())
            got = 0
            for i in range(n):
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

    def _write_probe(self, run_dir: Path, payload: dict) -> None:
        try:
            (run_dir / "fatal_probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
