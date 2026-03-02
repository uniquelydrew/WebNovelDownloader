import sys
import asyncio
import multiprocessing as mp

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from twisted.internet import asyncioreactor
try:
    asyncioreactor.install()
except Exception:
    pass

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    mp.freeze_support()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
