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

## Build (PyInstaller)
```bash
pip install -r requirements.txt
pyinstaller WebNovelScraper.spec
```
