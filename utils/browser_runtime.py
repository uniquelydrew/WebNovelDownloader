from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from utils.app_paths import app_data_root, ensure_dir


DEFAULT_CDP_HOST = "127.0.0.1"
DEFAULT_CDP_PORT = 9222
DEFAULT_BROWSER_URL = "https://www.wuxiaworld.com/"


@dataclass(frozen=True)
class BrowserLaunchResult:
    endpoint: str
    browser_executable: str | None
    profile_dir: str
    launched: bool
    already_running: bool


def cdp_port() -> int:
    return int(os.getenv("WNS_CDP_PORT", str(DEFAULT_CDP_PORT)))


def cdp_endpoint() -> str:
    host = os.getenv("WNS_CDP_HOST", DEFAULT_CDP_HOST).strip() or DEFAULT_CDP_HOST
    return f"http://{host}:{cdp_port()}"


def browser_profile_dir() -> Path:
    return ensure_dir(app_data_root() / "browser-profile")


def browser_launch_url() -> str:
    return os.getenv("WNS_BROWSER_URL", DEFAULT_BROWSER_URL).strip() or DEFAULT_BROWSER_URL


def is_cdp_ready(timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"{cdp_endpoint()}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("Browser"))
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def wait_for_cdp(timeout: float = 15.0, poll_interval: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_cdp_ready(timeout=min(1.0, poll_interval + 0.25)):
            return True
        time.sleep(poll_interval)
    return is_cdp_ready(timeout=1.0)


def _browser_candidates() -> list[Path]:
    env_paths = [
        os.getenv("WNS_BROWSER_EXE"),
        os.getenv("PROGRAMFILES"),
        os.getenv("PROGRAMFILES(X86)"),
        os.getenv("LOCALAPPDATA"),
    ]
    candidates: list[Path] = []

    explicit = os.getenv("WNS_BROWSER_EXE")
    if explicit:
        candidates.append(Path(explicit))

    bases = [Path(p) for p in env_paths[1:] if p]
    suffixes = [
        Path("Google/Chrome/Application/chrome.exe"),
        Path("Microsoft/Edge/Application/msedge.exe"),
        Path("Chromium/Application/chrome.exe"),
        Path("BraveSoftware/Brave-Browser/Application/brave.exe"),
    ]
    for base in bases:
        for suffix in suffixes:
            candidates.append(base / suffix)

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def find_browser_executable() -> Path:
    for candidate in _browser_candidates():
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "No supported browser executable was found. Set WNS_BROWSER_EXE to chrome.exe or msedge.exe."
    )


def launch_managed_browser(open_url: str | None = None) -> BrowserLaunchResult:
    if is_cdp_ready():
        return BrowserLaunchResult(
            endpoint=cdp_endpoint(),
            browser_executable=None,
            profile_dir=str(browser_profile_dir()),
            launched=False,
            already_running=True,
        )

    exe = find_browser_executable()
    profile_dir = browser_profile_dir()
    launch_url = (open_url or browser_launch_url()).strip() or browser_launch_url()

    cmd = [
        str(exe),
        f"--remote-debugging-port={cdp_port()}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        launch_url,
    ]

    creationflags = 0
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen_kwargs["close_fds"] = True

    subprocess.Popen(cmd, creationflags=creationflags, **popen_kwargs)

    if not wait_for_cdp():
        raise RuntimeError(
            f"Managed browser launch did not expose CDP at {cdp_endpoint()}. "
            f"Tried executable: {exe}"
        )

    return BrowserLaunchResult(
        endpoint=cdp_endpoint(),
        browser_executable=str(exe),
        profile_dir=str(profile_dir),
        launched=True,
        already_running=False,
    )


def ensure_managed_browser(open_url: str | None = None) -> BrowserLaunchResult:
    if is_cdp_ready():
        return BrowserLaunchResult(
            endpoint=cdp_endpoint(),
            browser_executable=None,
            profile_dir=str(browser_profile_dir()),
            launched=False,
            already_running=True,
        )
    return launch_managed_browser(open_url=open_url)
