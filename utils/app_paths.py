from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "WebNovelScraper"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return source_root()


def app_data_root() -> Path:
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata).resolve() / APP_NAME
    return (Path.home() / ".webnovel_scraper").resolve()


def writable_root() -> Path:
    return app_data_root() if is_frozen() else source_root()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_root() -> Path:
    return ensure_dir(writable_root() / "log")


def cache_root() -> Path:
    return ensure_dir(writable_root() / "cache")


def auth_root() -> Path:
    return ensure_dir(writable_root() / "auth")


def auth_storage_path() -> Path:
    return auth_root() / "storage_state.json"


def configure_playwright_env() -> Path | None:
    current = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if current:
        return Path(current)

    candidates = [
        bundle_root() / "playwright-browsers",
        source_root() / ".playwright-browsers",
        writable_root() / ".playwright-browsers",
    ]
    for candidate in candidates:
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return candidate
    return None


def build_crawl_command() -> list[str]:
    if is_frozen():
        return [sys.executable, "--run-crawl"]
    return [sys.executable, str(source_root() / "cli" / "run_crawl.py")]


def runtime_cwd() -> Path:
    return writable_root() if is_frozen() else source_root()
