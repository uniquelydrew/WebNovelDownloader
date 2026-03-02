from playwright.sync_api import sync_playwright
import time
from utils.rotating_logger import LineRotatingJSONLogger


class PlaywrightDiscoveryService:
    def __init__(self):
        self.logger = LineRotatingJSONLogger("logs/discovery.log")

    def load(self, url: str) -> dict:
        self.logger.log("discovery", "cdp_connect_attempt", {"url": url})

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            if not browser.contexts:
                raise RuntimeError("No Chrome contexts available on CDP connection.")
            context = browser.contexts[0]
            page = context.new_page()

            page.goto(url, timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=60000)

            self._wait_for_volume_toggles(page)

            payload = self._extract_series_payload(page, url)

            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

            self.logger.log(
                "discovery",
                "payload_complete",
                {"volumes": len(payload.get("volumes", [])),
                 "chapters": sum(len(v.get("chapters", [])) for v in payload.get("volumes", []))}
            )
            return payload

    def _wait_for_volume_toggles(self, page):
        page.wait_for_selector("button[aria-expanded]", timeout=60000)
        end = time.time() + 60.0
        last_count = -1
        stable = 0
        while time.time() < end:
            count = page.locator("button[aria-expanded]").count()
            if count == last_count:
                stable += 1
            else:
                stable = 0
            last_count = count
            if count > 0 and stable >= 5:
                return
            time.sleep(0.2)
        raise TimeoutError("Volume toggles did not stabilize.")

    def _extract_series_payload(self, page, url: str) -> dict:
        series_title = page.title()
        if series_title:
            series_title = series_title.strip()

        volumes = self._collect_volumes(page)

        out_volumes = []
        for i, vol in enumerate(volumes):
            title = (vol.get("title") or f"Volume {i+1}").strip()
            self.logger.log("discovery", "volume_begin", {"index": i, "title": title})

            self._ensure_expanded(page, vol["selector"])
            chapters = self._collect_chapters_for_volume(page, vol)

            out_volumes.append({
                "title": title,
                "chapters": chapters,
            })

            self.logger.log("discovery", "volume_done", {"index": i, "title": title, "chapters": len(chapters)})

        return {
            "series_title": series_title or "Unknown Series",
            "series_url": url,
            "volumes": out_volumes,
        }

    def _collect_volumes(self, page) -> list[dict]:
        # DOM-stable: rely on aria-expanded buttons, not CSS classes.
        # We also snapshot them into stable selectors based on nth index.
        btns = page.locator("button[aria-expanded]")
        n = btns.count()
        vols = []
        for i in range(n):
            b = btns.nth(i)
            text = (b.inner_text() or "").strip()
            # Stable selector: nth-of-type within button[aria-expanded] list
            selector = f"button[aria-expanded]:nth-of-type({i+1})"
            vols.append({"title": text, "selector": selector, "index": i})
        return vols

    def _ensure_expanded(self, page, button_selector: str):
        # React-safe: retry until aria-expanded becomes true (re-renders may replace nodes)
        for _ in range(20):
            btn = page.locator(button_selector).first
            try:
                btn.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            aria = btn.get_attribute("aria-expanded")
            if aria == "true":
                return
            try:
                btn.click(timeout=5000)
            except Exception:
                pass
            time.sleep(0.2)

        # Final check
        aria = page.locator(button_selector).first.get_attribute("aria-expanded")
        if aria != "true":
            raise RuntimeError(f"Failed to expand volume button: {button_selector}")

    def _collect_chapters_for_volume(self, page, vol: dict) -> list[dict]:
        # Volume panel discovery:
        # Prefer aria-controls to find controlled region.
        btn = page.locator(vol["selector"]).first
        panel_id = btn.get_attribute("aria-controls")
        if panel_id:
            panel = page.locator(f"#{panel_id}")
        else:
            # Fallback: nearest ancestor section and search within it
            panel = btn.locator("xpath=ancestor-or-self::*[self::div or self::section][1]")

        # Now collect chapter anchors while handling virtualization.
        # We consider chapter anchors any <a> with "/chapter/" in href.
        def snapshot():
            anchors = panel.locator("a[href*='/chapter/']")
            cnt = anchors.count()
            items = []
            for i in range(cnt):
                a = anchors.nth(i)
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or "").strip()
                if href.startswith("/"):
                    href = "https://www.wuxiaworld.com" + href
                if href and text:
                    items.append((text, href))
            # de-dupe preserving order
            seen = set()
            out = []
            for t, h in items:
                key = (t, h)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"title": t, "url": h})
            return out

        # Wait until at least 1 chapter link appears (React-safe)
        end = time.time() + 60.0
        while time.time() < end:
            ch = snapshot()
            if ch:
                break
            time.sleep(0.2)

        # Virtualization handling: scroll the panel (or window) until no growth
        prev = -1
        stable = 0
        chapters = snapshot()
        for _ in range(120):
            cur = len(chapters)
            if cur == prev:
                stable += 1
            else:
                stable = 0
            prev = cur
            if stable >= 6:
                break

            # Try panel scroll first
            try:
                page.evaluate(
                    """(el) => { el.scrollTop = el.scrollHeight; }""",
                    panel.element_handle()
                )
            except Exception:
                try:
                    page.mouse.wheel(0, 3000)
                except Exception:
                    pass

            time.sleep(0.25)
            chapters = snapshot()

        # Optional: normalize chapter indexes if desired later
        return chapters