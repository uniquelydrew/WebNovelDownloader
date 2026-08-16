# WebNovelScraper

Volume-scoped web novel scraper/exporter.

## Run GUI
```bash
python gui/app.py
```

## Environment Variables (Auth)
- `NOVEL_AUTH_BEARER` (optional)
- `NOVEL_AUTH_COOKIE` (optional)
- `NOVEL_USER_AGENT` (optional)
- `WN_USERNAME` / `WN_PASSWORD` for `--bootstrap-auth`
- `WNS_BROWSER_EXE` to point at a specific `chrome.exe` or `msedge.exe`
- `WNS_BROWSER_URL` to override the default page opened by the managed browser
- `WNS_CDP_PORT` to override the remote debugging port (default `9222`)

## Managed Browser
- The app can now launch a managed Chrome/Edge instance automatically with the required remote debugging configuration.
- The browser profile lives under `%LOCALAPPDATA%\WebNovelScraper\browser-profile`.
- Use the `Launch Browser` button or just click `Load`/`Export`; the app will start the browser if needed.

## Preferences
- The app now stores user preferences in `%LOCALAPPDATA%\WebNovelScraper\preferences.json`.
- Use `Edit > Preferences` to set a persistent workspace root for the whole app.
- The `Windows` menu can raise the main window and the Preferences window if they are hidden.
- Optional per-widget background/text color overrides can be enabled in Preferences. They are off by default.

## Windows PyInstaller Build
```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path (Get-Location) '.playwright-browsers')
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m PyInstaller --noconfirm WebNovelScraper.spec
```

Or use the helper script:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -Clean
```

## Windows Runtime Notes
- The frozen app stores writable state under `%LOCALAPPDATA%\WebNovelScraper`.
- Workspaces live under the workspace root configured in Preferences. If no preference is set, the default is `%LOCALAPPDATA%\WebNovelScraper\workspaces`.
- If you bundle Playwright browsers, keep `playwright-browsers` inside the built distribution.
