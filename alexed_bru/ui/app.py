# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Application bootstrap."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from alexed_bru import APP_NAME, APP_VERSION
from alexed_bru.paths import resource_path


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
    # Show the logo at once. Building the window needs Qt's font list, which
    # takes seconds on PCs with thousands of installed fonts.
    splash = QSplashScreen(QPixmap(str(resource_path("assets/branding/png/logo-mark-128.png"))),
                           Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    import alexed_bru.skills  # noqa: F401  (register built-in skills)
    from alexed_bru.ui.main_window import MainWindow
    from alexed_bru.ui.theme import apply_theme

    apply_theme(app)
    window = MainWindow()
    window.show()
    splash.finish(window)
    # Files/folders passed on the command line (or dropped onto the exe).
    from pathlib import Path
    paths = [Path(a) for a in argv[1:] if Path(a).exists()]
    if paths:
        window.add_paths(paths)
    return app.exec()
