from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from twisted.internet import reactor, defer

from spiders.novel import NovelSpider
from export.bundle import VolumeExportBundle
from export.service import ExportService
from models.metadata import SeriesMetadata

class CrawlerWorker(QThread):
    progress_changed = Signal(int)
    status_message = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, index_url: str, output_dir: str, fmt: str):
        super().__init__()
        self.index_url = index_url
        self.output_dir = output_dir
        self.fmt = fmt

    def run(self):
        try:
            self.status_message.emit("Starting crawl...")
            settings = get_project_settings()
            runner = CrawlerRunner(settings)

            collected = []
            series_holder = {}
            total_counter = {"done": 0, "total": 1}

            class CaptureSpider(NovelSpider):
                def parse_index(self_inner, response):
                    series = self_inner.parser.parse(response)
                    series_holder["series"] = series
                    total_counter["total"] = max(1, sum(len(v.chapters) for v in series.volumes))
                    return super().parse_index(response)

                def parse_chapter(self_inner, response):
                    item = super().parse_chapter(response)
                    if item is not None:
                        collected.append(item)
                        total_counter["done"] += 1
                        pct = int((total_counter["done"] / total_counter["total"]) * 100)
                        self.progress_changed.emit(min(100, max(0, pct)))
                    return item

            @defer.inlineCallbacks
            def _crawl():
                yield runner.crawl(CaptureSpider, index_url=self.index_url, out_dir=self.output_dir)
                reactor.stop()

            _crawl()
            reactor.run(installSignalHandlers=False)

            series = series_holder.get("series")
            if series is None:
                self.finished_signal.emit(False, "Failed: no series parsed from index page.")
                return

            self.status_message.emit("Building volume exports...")
            metadata = SeriesMetadata(title=series.title)
            bundles = []
            for volume in series.volumes:
                vol_chapters = [c for c in collected if c.volume_index == volume.index]
                if not vol_chapters:
                    continue
                bundles.append(VolumeExportBundle(metadata=metadata, volume=volume, chapters=vol_chapters))

            ExportService().export_volumes(bundles, output_dir=self.output_dir, fmt=self.fmt)

            self.progress_changed.emit(100)
            self.finished_signal.emit(True, "Export completed.")
        except Exception as e:
            self.finished_signal.emit(False, f"{type(e).__name__}: {e}")
