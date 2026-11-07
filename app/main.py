"""Application entry point."""
from __future__ import annotations

import logging
import os
import sys
import traceback


def main():
    if sys.platform == "win32":
        try:  # taskbar groups under our own icon instead of python.exe
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NovaMacroHub.App")
        except Exception:
            pass

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .core.storage import data_dir
    from .engine import Engine
    from .ui.main_window import MainWindow

    logging.basicConfig(filename=str(data_dir() / "app.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    app = QApplication(sys.argv)
    app.setApplicationName("Nova Macro Hub")
    app.setQuitOnLastWindowClosed(False)

    # Only one copy may run, otherwise scheduled messages could be sent twice.
    lock = QLockFile(str(data_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Nova Macro Hub", "Nova Macro Hub is already running.\n\n"
                                "Look for its icon in the system tray (bottom-right, maybe under the ^ arrow).")
        return 0

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error(text)
        try:
            QMessageBox.critical(None, "Unexpected error", f"{exc}\n\nDetails were saved to {data_dir() / 'app.log'}")
        except Exception:
            pass

    sys.excepthook = excepthook

    engine = Engine()
    win = MainWindow(engine)
    start_hidden = "--minimized" in sys.argv or engine.storage.get_setting("start_minimized")
    if not (start_hidden and hasattr(win, "tray")):
        win.showMaximized()
    code = app.exec()
    win._shutdown()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
