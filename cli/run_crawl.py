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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True, help="Path to selection JSON produced by GUI")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--format", choices=["epub", "pdf"], required=True, help="Export format")
    args = ap.parse_args(argv)

    try:
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    except Exception as e:
        _print_event({"type": "error", "message": f"Failed to read selection: {type(e).__name__}: {e}"})
        return 2

    items = sel.get("chapters", []) or []
    selection_series_title = str(sel.get("series_title") or "Unknown Series")
    for it in items:
        it.setdefault("series_title", selection_series_title)
    total = int(sel.get("total_chapters", len(items))) or len(items)
    _print_event({"type": "status", "message": f"Starting crawl of {total} chapter(s)..."})

    cleaner = Cleaner(CleanerConfig(aside_mode="balanced", remove_footnote_markers=True))
    crawler = PlaywrightChapterCrawler()

    filesystem_pipeline = FilesystemPipeline()
    workspace_root, workspace_project = _resolve_workspace_project(sel)

    class _Shim:
        out_dir = args.out_dir
        workspace_dir = str(workspace_root) if workspace_root else None
        series_title = selection_series_title
        language = str(sel.get("language", "en") or "en")

    filesystem_pipeline.open_spider(_Shim())
    workspace_pipeline = None
    if workspace_root and workspace_project is not None:
        workspace_pipeline = EpubWorkspacePipeline()
        workspace_pipeline.open_spider(_Shim())
        _print_event({"type": "status", "message": f"Workspace persistence enabled: {workspace_root}"})

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

    try:
        done = 0
        for ch in crawler.fetch_chapters(items, cleaner=cleaner):
            filesystem_pipeline.process_item(ch, _Shim())
            if workspace_pipeline is not None:
                workspace_pipeline.process_item(ch, _Shim())

            if current_volume_index is None:
                current_volume_index = ch.volume_index
                current_volume_title = ch.volume_title
            elif ch.volume_index != current_volume_index:
                flush_current_volume()
                current_volume_index = ch.volume_index
                current_volume_title = ch.volume_title

            current_volume_chapters.append(ch)
            done += 1
            msg = f"Fetched {ch.volume_title} / {ch.chapter_title}"
            _print_event({"type": "progress", "done": done, "total": total, "message": msg})

        flush_current_volume()
    except Exception as e:
        _print_event({"type": "error", "message": f"Crawl failed: {type(e).__name__}: {e}"})
        return 3
    finally:
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

    _print_event({"type": "status", "message": f"Exported {len(exported_paths)} file(s)."})
    _print_event({"type": "status", "message": "Crawl subprocess finished."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())