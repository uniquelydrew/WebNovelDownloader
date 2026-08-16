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
from workspaces.epub_project import EpubWorkspaceProject
from workspaces.manager import WorkspaceManager
from workspaces.pipeline import EpubWorkspacePipeline


def _print_event(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _resolve_workspace_project(selection: dict) -> tuple[Path | None, EpubWorkspaceProject | None]:
    series_url = str(selection.get("series_url") or "").strip()
    series_title = str(selection.get("series_title") or "Unknown Series").strip() or "Unknown Series"
    if not series_url:
        return None, None

    try:
        ws_mgr = WorkspaceManager()
        paths = ws_mgr.ensure(series_url, series_title)
        return paths.root, EpubWorkspaceProject(paths.root)
    except Exception:
        return None, None


def _sorted_selection_items(selection: dict) -> list[dict]:
    items = list(selection.get("chapters", []) or [])
    items.sort(key=lambda it: (int(it.get("volume_index") or 0), int(it.get("chapter_index") or 0)))
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True, help="Path to selection JSON produced by GUI")
    ap.add_argument("--out-dir", default="", help="Output directory")
    ap.add_argument("--format", choices=["epub", "pdf"], required=True, help="Export format")
    ap.add_argument("--download-only", action="store_true", help="Cache missing chapters without exporting files")
    ap.add_argument("--download-tabs", type=int, choices=range(1, 5), default=1, help="Managed Chrome tabs used for chapter fetches (1-4)")
    args = ap.parse_args(argv)

    try:
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    except Exception as e:
        _print_event({"type": "error", "message": f"Failed to read selection: {type(e).__name__}: {e}"})
        return 2

    items = _sorted_selection_items(sel)
    selection_series_title = str(sel.get("series_title") or "Unknown Series")
    for it in items:
        it.setdefault("series_title", selection_series_title)
    total = int(sel.get("total_chapters", len(items))) or len(items)
    _print_event({"type": "status", "message": f"Starting crawl of {total} chapter(s) with {args.download_tabs} download tab(s)..."})

    filesystem_pipeline = FilesystemPipeline() if not args.download_only else None
    workspace_root, workspace_project = _resolve_workspace_project(sel)

    class _Shim:
        out_dir = args.out_dir
        workspace_dir = str(workspace_root) if workspace_root else None
        series_title = selection_series_title
        language = str(sel.get("language", "en") or "en")

    if filesystem_pipeline is not None:
        filesystem_pipeline.open_spider(_Shim())
    workspace_pipeline = None
    if workspace_root and workspace_project is not None:
        workspace_pipeline = EpubWorkspacePipeline()
        workspace_pipeline.open_spider(_Shim())
        _print_event({"type": "status", "message": f"Workspace persistence enabled: {workspace_root}"})

    min_chars = int(sel.get("min_chapter_chars") or 500)
    cached_by_url: dict[str, Chapter] = {}
    pending_items: list[dict] = []
    seen_urls: set[str] = set()
    if workspace_project is not None:
        for item in items:
            item_url = str(item.get("url") or "").strip()
            if not item_url or item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            cached = workspace_project.load_cached_chapter(
                series_title=selection_series_title,
                volume_index=int(item.get("volume_index") or 0),
                volume_title=str(item.get("volume_title") or f"Volume {int(item.get('volume_index') or 0)}"),
                chapter_index=int(item.get("chapter_index") or 0),
                chapter_title=str(item.get("chapter_title") or ""),
                url=item_url,
                min_chars=min_chars,
            )
            if cached is None:
                pending_items.append(item)
                continue
            cached_by_url[cached.chapter_url] = cached
    else:
        for item in items:
            item_url = str(item.get("url") or "").strip()
            if item_url and item_url not in seen_urls:
                seen_urls.add(item_url)
                pending_items.append(item)

    if cached_by_url:
        _print_event(
            {
                "type": "status",
                "message": f"Reusing {len(cached_by_url)} cached chapter(s) from workspace EPUB.",
            }
        )
    if pending_items:
        _print_event(
            {
                "type": "status",
                "message": f"Fetching {len(pending_items)} chapter(s) from the site because content is missing or suspect.",
            }
        )
    else:
        _print_event({"type": "status", "message": "All selected chapters were satisfied from the workspace cache."})

    meta = SeriesMetadata(
        title=selection_series_title,
        author=sel.get("series_author"),
        description=sel.get("series_description"),
        language=sel.get("language", "en") or "en",
    )
    svc = ExportService()
    exported_paths: list[str] = []
    current_volume_index: int | None = None
    current_volume_title: str | None = None
    current_volume_chapters: list[Chapter] = []
    done = 0

    def flush_current_volume() -> None:
        nonlocal current_volume_index, current_volume_title, current_volume_chapters

        if current_volume_index is None or not current_volume_chapters:
            return

        volume = Volume(
            index=int(current_volume_index),
            title=str(current_volume_title or f"Volume {current_volume_index}"),
            chapters=[],
        )
        bundle = VolumeExportBundle(
            metadata=meta,
            volume=volume,
            chapters=sorted(current_volume_chapters, key=lambda c: c.chapter_index),
        )
        path = svc.export_volume(bundle, output_dir=args.out_dir, fmt=args.format)
        exported_paths.append(path)
        _print_event({"type": "export", "path": path})
        _print_event({"type": "status", "message": f"Exported {volume.title}."})
        current_volume_index = None
        current_volume_title = None
        current_volume_chapters = []

    def process_chapter(ch: Chapter, *, fetched_from_site: bool) -> None:
        nonlocal current_volume_index, current_volume_title, current_volume_chapters, done

        if filesystem_pipeline is not None:
            filesystem_pipeline.process_item(ch, _Shim())
        if fetched_from_site and workspace_pipeline is not None:
            workspace_pipeline.process_item(ch, _Shim())

        if args.download_only:
            done += 1
            _print_event({"type": "progress", "done": done, "total": total, "message": f"{'Fetched' if fetched_from_site else 'Reused cached'} {ch.chapter_title}"})
            return
        if current_volume_index is None:
            current_volume_index = ch.volume_index
            current_volume_title = ch.volume_title
        elif ch.volume_index != current_volume_index:
            flush_current_volume()
            current_volume_index = ch.volume_index
            current_volume_title = ch.volume_title

        current_volume_chapters.append(ch)
        done += 1
        action = "Fetched" if fetched_from_site else "Reused cached"
        _print_event(
            {
                "type": "progress",
                "done": done,
                "total": total,
                "message": f"{action} {ch.volume_title} / {ch.chapter_title}",
            }
        )

    fetched_by_url: dict[str, Chapter] = {}
    crawler = None
    if pending_items:
        cleaner = Cleaner(CleanerConfig(aside_mode="balanced", remove_footnote_markers=True))
        crawler = PlaywrightChapterCrawler(download_tabs=args.download_tabs)

    try:
        if crawler is not None:
            fetched_count = 0
            fetch_total = len(pending_items)
            for ch in crawler.fetch_chapters(pending_items, cleaner=cleaner):
                fetched_by_url[ch.chapter_url] = ch
                fetched_count += 1
                _print_event(
                    {
                        "type": "progress",
                        "done": fetched_count,
                        "total": fetch_total,
                        "message": f"Downloaded {fetched_count}/{fetch_total}: {ch.volume_title} / {ch.chapter_title}",
                    }
                )

        for item in items:
            url = str(item.get("url") or "").strip()
            chapter = cached_by_url.get(url) or fetched_by_url.get(url)
            if chapter is None:
                continue
            process_chapter(chapter, fetched_from_site=url in fetched_by_url)

        if not args.download_only:
            flush_current_volume()
    except Exception as e:
        _print_event({"type": "error", "message": f"Crawl failed: {type(e).__name__}: {e}"})
        return 3
    finally:
        if crawler is not None:
            try:
                crawler.close()
            except Exception:
                pass

    if workspace_project is not None:
        try:
            workspace_project.finalize_and_repair(
                language=str(sel.get("language", "en") or "en"),
                series_title=selection_series_title,
                author=sel.get("series_author"),
                description=sel.get("series_description"),
            )
            _print_event({"type": "status", "message": "Workspace repair/finalization complete."})
        except Exception as e:
            _print_event({"type": "status", "message": f"Workspace finalization failed: {type(e).__name__}: {e}"})

    _print_event({"type": "status", "message": "Download complete." if args.download_only else f"Exported {len(exported_paths)} file(s)."})
    _print_event({"type": "status", "message": "Crawl subprocess finished."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
