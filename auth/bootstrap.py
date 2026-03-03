import os
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_DIR = PROJECT_ROOT / "auth"
AUTH_DIR.mkdir(exist_ok=True)
STORAGE_PATH = AUTH_DIR / "storage_state.json"


def bootstrap(login_url: str):
    username = os.getenv("WN_USERNAME")
    password = os.getenv("WN_PASSWORD")

    if not username or not password:
        raise RuntimeError("WN_USERNAME and WN_PASSWORD must be set.")

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-url", required=True)
    args = parser.parse_args()
    bootstrap(args.login_url)
