from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from pathlib import Path
import time
import json
import os

from utils.rotating_logger import LineRotatingJSONLogger


class PlaywrightDiscoveryService:
    def __init__(self):
        self.logger = LineRotatingJSONLogger("logs/discovery.log")

    def load(self, url: str) -> dict:
        run_dir = self._make_run_dir()
        console_path = run_dir / "console.jsonl"

        def on_console(msg):
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
                pass

        self.logger.log("discovery", "cdp_connect_attempt", {"url": url})

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

                payload = self._extract_payload(page, url)

                self.logger.log(
                    "discovery",
                    "payload_complete",
                    {
                        "debug_run_dir": str(run_dir),
                        "volumes": len(payload.get("volumes", [])),
                        "chapters": sum(len(v.get("chapters", [])) for v in payload.get("volumes", [])),
                    },
                )

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

    def _extract_payload(self, page, url: str) -> dict:
        series_title = (page.title() or "").strip() or "Unknown Series"

        toggles = page.locator("[role='button'][aria-expanded]")
        count = toggles.count()

        volumes = []

        for i in range(count):
            toggle = toggles.nth(i)

            try:
                toggle.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            if toggle.get_attribute("aria-expanded") == "false":
                try:
                    toggle.click(timeout=5000)
                except Exception:
                    pass

                for _ in range(20):
                    try:
                        if toggle.get_attribute("aria-expanded") == "true":
                            break
                    except Exception:
                        pass
                    time.sleep(0.1)

            vol_title = (toggle.inner_text() or "").strip() or f"Volume {i+1}"

            panel_id = None
            try:
                panel_id = toggle.get_attribute("aria-controls")
            except Exception:
                panel_id = None

            if panel_id:
                panel = page.locator(f"#{panel_id}")
            else:
                panel = page

            chapters = self._collect_chapters(page, panel, url)

            if chapters:
                volumes.append({"title": vol_title, "chapters": chapters})

        return {
            "debug_run_dir": None,
            "series_title": series_title,
            "series_url": url,
            "volumes": volumes,
        }

    from urllib.parse import urlparse

    def _collect_chapters(self, page, scope, series_url: str) -> list[dict]:
        parsed = urlparse(series_url)
        parts = [p for p in parsed.path.split("/") if p]
        series_slug = parts[-1] if parts else ""

        anchors = scope.locator("a[href*='/novel/']")

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

        items = []
        seen = set()
        n = anchors.count()
        base_prefix = f"/novel/{series_slug}" if series_slug else ""

        for i in range(n):
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()

            if not href:
                continue

            if href.startswith("/"):
                abs_href = "https://www.wuxiaworld.com" + href
            else:
                abs_href = href

            if base_prefix:
                if href.startswith("/") and not href.startswith(base_prefix + "/"):
                    continue
                if href == base_prefix:
                    continue

            if not text:
                text = abs_href

            key = (text, abs_href)
            if key in seen:
                continue
            seen.add(key)

            items.append({"title": text, "url": abs_href})

        return items

    def _make_run_dir(self) -> Path:
        root = Path("logs") / "debug_runs"
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
