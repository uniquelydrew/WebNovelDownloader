from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from scrapy.crawler import CrawlerProcess

# Ensure Scrapy uses our settings module in this repo
os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "settings")

from spiders.selected_spider import SelectedSpider  # noqa: E402


def _print_event(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True, help="Path to selection JSON produced by GUI")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--format", choices=["epub", "pdf"], required=True, help="Export format")
    args = ap.parse_args(argv)

    # Validate selection file exists early
    try:
        with open(args.selection, "r", encoding="utf-8") as f:
            sel = json.load(f)
    except Exception as e:
        _print_event({"type": "error", "message": f"Failed to read selection: {type(e).__name__}: {e}"})
        return 2

    total = int(sel.get("total_chapters", 0)) or 0
    _print_event({"type": "status", "message": f"Starting crawl of {total} chapter(s)..."})

    process = CrawlerProcess()  # uses settings.py via SCRAPY_SETTINGS_MODULE
    process.crawl(
        SelectedSpider,
        selection_path=args.selection,
        out_dir=args.out_dir,
        export_format=args.format,
    )
    try:
        process.start()
    except Exception as e:
        _print_event({"type": "error", "message": f"Crawl failed: {type(e).__name__}: {e}"})
        return 3

    _print_event({"type": "status", "message": "Crawl subprocess finished."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
