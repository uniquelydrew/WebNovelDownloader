from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scrapy
from scrapy.http import Response

from clean.cleaner import Cleaner, CleanerConfig
from extract.content import find_content_container, extract_text
from export.bundle import VolumeExportBundle
from export.service import ExportService
from models.chapter import Chapter
from models.metadata import SeriesMetadata
from models.volume import Volume


class SelectedSpider(scrapy.Spider):
    name = "selected"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_DELAY": 0.15,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "COOKIES_ENABLED": True,
        # We still write per-chapter folders (chapter.txt + meta.json)
        "ITEM_PIPELINES": {"pipelines.filesystem.FilesystemPipeline": 300},
        # Keep logs quieter; GUI uses structured events from stdout
        "LOG_LEVEL": "INFO",
        "DOWNLOADER_MIDDLEWARES": {
            "auth.middleware.StorageStateCookieMiddleware": 543,
        },
    }

    def __init__(self, selection_path: str, out_dir: str, export_format: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection_path = selection_path
        self.out_dir = out_dir
        self.export_format = export_format

        self.cleaner = Cleaner(CleanerConfig(aside_mode="balanced", remove_footnote_markers=True))

        sel = json.loads(Path(selection_path).read_text(encoding="utf-8"))
        self.series_title = sel.get("series_title", "Unknown Series")
        self.series_author = sel.get("series_author")
        self.series_description = sel.get("series_description")
        self.language = sel.get("language", "en")
        self.items = sel.get("chapters", [])
        self.total = int(sel.get("total_chapters", len(self.items))) or len(self.items)

        # Accumulate for export (volume-scoped)
        self._chapters: list[Chapter] = []
        self._volumes: dict[int, str] = {}  # index->title
        self._done = 0

    def start_requests(self):
        for item in self.items:
            yield scrapy.Request(
                url=item["url"],
                callback=self.parse_chapter,
                meta=item,
            )

    def parse_chapter(self, response: Response):
        meta = response.meta
        # Hard unauthorized fast-fail
        preview_markers = [
            "Log in to continue your adventure",
            "Unlock free chapters every day",
            "Other benefits you will get",
        ]

        for marker in preview_markers:
            if marker in response.text:
                raise RuntimeError(
                    f"Unauthorized preview page detected: {response.url}"
                )

        container = find_content_container(response)
        if not container:
            # Still emit progress so GUI doesn't look frozen
            self._done += 1
            self._emit_progress(f"Missing content container for {response.url}")
            return None

        raw = extract_text(container)

        # Aggressively remove blockquotes
        from lxml import html

        doc = html.fromstring(response.text)
        for node in doc.xpath("//blockquote"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

        cleaned_html = html.tostring(doc, encoding="unicode")

        clean = self.cleaner.clean(raw)

        # Minimum length guard
        if len(clean.strip()) < 500:
            raise RuntimeError(
                f"Chapter content too short (possible preview): {response.url}"
            )

        ch = Chapter(
            novel_title=self.series_title,
            volume_index=int(meta["volume_index"]),
            volume_title=str(meta["volume_title"]),
            chapter_index=int(meta["chapter_index"]),
            chapter_title=str(meta["chapter_title"]).strip() or f"Chapter {meta['chapter_index']}",
            chapter_url=response.url,
            text=clean,
        )

        self._chapters.append(ch)
        self._volumes[ch.volume_index] = ch.volume_title

        self._done += 1
        self._emit_progress(f"Fetched {ch.volume_title} / {ch.chapter_title}")
        return ch

    def _emit_progress(self, msg: str) -> None:
        # Structured line that GUI worker parses.
        self.logger.info("PROGRESS %s/%s %s", self._done, self.total, msg)
        print(json.dumps({"type": "progress", "done": self._done, "total": self.total, "message": msg}, ensure_ascii=False), flush=True)

    def closed(self, reason: str):
        # Export volume-scoped files after crawl
        meta = SeriesMetadata(
            title=self.series_title,
            author=self.series_author,
            description=self.series_description,
            language=self.language or "en",
        )

        bundles: list[VolumeExportBundle] = []
        for vol_index, vol_title in sorted(self._volumes.items(), key=lambda x: x[0]):
            volume = Volume(index=int(vol_index), title=str(vol_title), chapters=[])
            vol_chaps = [c for c in self._chapters if c.volume_index == int(vol_index)]
            if not vol_chaps:
                continue
            bundles.append(VolumeExportBundle(metadata=meta, volume=volume, chapters=sorted(vol_chaps, key=lambda c: c.chapter_index)))

        svc = ExportService()
        paths = svc.export_volumes(bundles, output_dir=self.out_dir, fmt=self.export_format)

        print(json.dumps({"type": "status", "message": f"Exported {len(paths)} file(s)."}, ensure_ascii=False), flush=True)
        for p in paths:
            print(json.dumps({"type": "export", "path": p}, ensure_ascii=False), flush=True)
