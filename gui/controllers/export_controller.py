from __future__ import annotations

from collections.abc import Callable

from services.subprocess_worker import SubprocessCrawlWorker


class ExportController:
    def __init__(self):
        self.worker: SubprocessCrawlWorker | None = None

    def start(
        self,
        payload: dict,
        out_dir: str,
        fmt: str,
        *,
        on_progress: Callable[[int, int, str], None],
        on_status: Callable[[str], None],
        on_log: Callable[[str], None],
        on_finished: Callable[[bool, str], None],
    ) -> None:
        self.worker = SubprocessCrawlWorker(payload, out_dir, fmt)
        self.worker.progress.connect(on_progress)
        self.worker.status.connect(on_status)
        self.worker.log.connect(on_log)
        self.worker.finished.connect(on_finished)
        self.worker.start()

    def start_download(
        self,
        payload: dict,
        *,
        on_progress: Callable[[int, int, str], None],
        on_status: Callable[[str], None],
        on_log: Callable[[str], None],
        on_finished: Callable[[bool, str], None],
    ) -> None:
        self.worker = SubprocessCrawlWorker(payload, "", "epub", download_only=True)
        self.worker.progress.connect(on_progress)
        self.worker.status.connect(on_status)
        self.worker.log.connect(on_log)
        self.worker.finished.connect(on_finished)
        self.worker.start()
