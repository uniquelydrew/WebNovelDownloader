import sys
import asyncio
import multiprocessing as mp

from utils.app_paths import configure_playwright_env


def _configure_windows_event_loop(*, gui_mode: bool) -> None:
    if not sys.platform.startswith("win"):
        return
    if gui_mode:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    else:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _install_twisted_asyncio_reactor() -> None:
    from twisted.internet import asyncioreactor

    try:
        asyncioreactor.install()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    mp.freeze_support()
    configure_playwright_env()

    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else None

    if command == "--run-crawl":
        _configure_windows_event_loop(gui_mode=False)
        from cli.run_crawl import main as run_crawl_main

        return int(run_crawl_main(argv[1:]))

    if command == "--bootstrap-auth":
        _configure_windows_event_loop(gui_mode=False)
        from auth.bootstrap import main as auth_main

        return int(auth_main(argv[1:]))

    _configure_windows_event_loop(gui_mode=True)
    _install_twisted_asyncio_reactor()

    from PySide6.QtWidgets import QApplication
    from gui.main_window import MainWindow

    app = QApplication([sys.argv[0], *argv])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
