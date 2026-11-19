# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Application bootstrap."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from alexed_bru import APP_NAME, APP_VERSION
from alexed_bru.paths import resource_path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    # Privacy: the app never writes log files. Libraries that log (Pillow, mutagen...) go to a
    # NullHandler, so nothing reaches the disk or a console.
    import logging
    logging.basicConfig(handlers=[logging.NullHandler()], force=True)
    logging.lastResort = None
    if sys.platform == "win32":
        try:  # own taskbar icon/group instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Alexbed.BulkRenameUtility")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(argv)
    # One window: if this copy is already open (e.g. this launch came from Explorer's Send To),
    # hand it the files and quit before showing anything.
    from alexed_bru.ui.single_instance import InstanceServer, send_to_running
    files = [a for a in argv[1:] if os.path.exists(a)]
    if send_to_running([os.path.abspath(a) for a in files]):
        return 0
    # Listen at once (building the window takes seconds); files that arrive meanwhile wait.
    server = InstanceServer()
    early: list[str] = []
    server.filesReceived.connect(early.extend)
    server.start()  # if it can't listen, later launches just open their own window
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
    server.setParent(window)
    server.filesReceived.disconnect()
    server.filesReceived.connect(window.receive_files)
    if early:
        window.receive_files(early)
    # Files/folders passed on the command line (or dropped onto the exe).
    from pathlib import Path
    paths = [Path(a) for a in argv[1:] if Path(a).exists()]
    if paths:
        window.add_paths(paths)
    return app.exec()
