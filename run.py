# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point for development (python run.py) and for PyInstaller."""
from alexed_bru.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
