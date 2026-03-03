from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clean.cleaner import Cleaner, CleanerConfig
from export.bundle import VolumeExportBundle
from export.service import ExportService
from models.chapter import Chapter
from models.metadata import SeriesMetadata
from models.volume import Volume
from pipelines.filesystem import FilesystemPipeline
from services.playwright_chapter_crawler import PlaywrightChapterCrawler


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
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    except Exception as e:
        _print_event({"type": "error", "message": f"Failed to read selection: {type(e).__name__}: {e}"})
        return 2

    items = sel.get("chapters", []) or []
    # Enrich per-chapter metadata for downstream consumers
    series_title = sel.get("series_title", "Unknown Series")
    for it in items:
        it.setdefault("series_title", series_title)
    total = int(sel.get("total_chapters", len(items))) or len(items)
    _print_event({"type": "status", "message": f"Starting crawl of {total} chapter(s)..."})

    cleaner = Cleaner(CleanerConfig(aside_mode="balanced", remove_footnote_markers=True))

    crawler = PlaywrightChapterCrawler()

    pipeline = FilesystemPipeline()
    # minimal spider-like shim for pipeline compatibility
    class _Shim:
        out_dir = args.out_dir
    pipeline.open_spider(_Shim())

    chapters: list[Chapter] = []
    volumes: dict[int, str] = {}

    try:
        done = 0
        for ch in crawler.fetch_chapters(items, cleaner=cleaner):
            pipeline.process_item(ch, _Shim())
            chapters.append(ch)
            volumes[ch.volume_index] = ch.volume_title
            done += 1
            msg = f"Fetched {ch.volume_title} / {ch.chapter_title}"
            _print_event({"type": "progress", "done": done, "total": total, "message": msg})
    except Exception as e:
        _print_event({"type": "error", "message": f"Crawl failed: {type(e).__name__}: {e}"})
        return 3
    finally:
        try:
            crawler.close()
        except Exception:
            pass

    # Export volume-scoped files after crawl
    meta = SeriesMetadata(
        title=sel.get("series_title", "Unknown Series"),
        author=sel.get("series_author"),
        description=sel.get("series_description"),
        language=sel.get("language", "en") or "en",
    )

    bundles: list[VolumeExportBundle] = []
    for vol_index, vol_title in sorted(volumes.items(), key=lambda x: x[0]):
        volume = Volume(index=int(vol_index), title=str(vol_title), chapters=[])
        vol_chaps = [c for c in chapters if c.volume_index == int(vol_index)]
        if not vol_chaps:
            continue
        bundles.append(
            VolumeExportBundle(
                metadata=meta,
                volume=volume,
                chapters=sorted(vol_chaps, key=lambda c: c.chapter_index),
            )
        )

    svc = ExportService()
    try:
        paths = svc.export_volumes(bundles, output_dir=args.out_dir, fmt=args.format)
    except Exception as e:
        _print_event({"type": "error", "message": f"Export failed: {type(e).__name__}: {e}"})
        return 4

    _print_event({"type": "status", "message": f"Exported {len(paths)} file(s)."})
    for p in paths:
        _print_event({"type": "export", "path": p})

    _print_event({"type": "status", "message": "Crawl subprocess finished."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
