"""Application bootstrap."""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import alexed_bru.skills  # noqa: F401  (register built-in skills)
from alexed_bru import APP_NAME, APP_VERSION
from alexed_bru.paths import resource_path
from alexed_bru.ui.main_window import MainWindow
from alexed_bru.ui.theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if sys.platform == "win32":
        try:  # own taskbar icon/group instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Alexed.BulkRenameUtility")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(resource_path("assets/branding/app.ico"))))
    apply_theme(app)
    window = MainWindow()
    window.show()
    # Files/folders passed on the command line (or dropped onto the exe).
    from pathlib import Path
    paths = [Path(a) for a in argv[1:] if Path(a).exists()]
    if paths:
        window.add_paths(paths)
    return app.exec()
