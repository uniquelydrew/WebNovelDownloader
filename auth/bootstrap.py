from __future__ import annotations

import argparse
import os

from playwright.sync_api import sync_playwright

from utils.app_paths import auth_root, auth_storage_path, configure_playwright_env


AUTH_DIR = auth_root()
STORAGE_PATH = auth_storage_path()


def bootstrap(login_url: str) -> None:
    username = os.getenv("WN_USERNAME")
    password = os.getenv("WN_PASSWORD")

    if not username or not password:
        raise RuntimeError("WN_USERNAME and WN_PASSWORD must be set.")

    configure_playwright_env()
    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(login_url)
        page.fill("input[type='email'], input[name='email']", username)
        page.fill("input[type='password'], input[name='password']", password)
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")

        context.storage_state(path=str(STORAGE_PATH))
        print(f"[AUTH] storage_state.json saved to {STORAGE_PATH}")

        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-url", required=True)
    args = parser.parse_args(argv)
    bootstrap(args.login_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
