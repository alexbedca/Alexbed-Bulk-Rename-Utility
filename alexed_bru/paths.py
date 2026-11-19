# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable storage locations.

Everything the app persists (history, presets, settings) lives in a folder
next to the executable, so the app leaves no registry or AppData footprint. If that
folder is not writable (for example, the exe runs from a read-only share), we
fall back to a per-user folder.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

DATA_FOLDER_NAME = "AlexbedBRU_data"
# Before 1.1.1 the app was misnamed "Alexed": keep using an existing folder of the old name,
# so nobody loses their history, presets or settings.
OLD_DATA_FOLDER_NAME = "AlexedBRU_data"
ENV_VARS = ("ALEXBED_BRU_DATA", "ALEXED_BRU_DATA")  # new name first; the old one still works


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Locate bundled read-only resources (works inside a PyInstaller onefile)."""
    base = Path(getattr(sys, "_MEIPASS", app_root()))
    return base / relative


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def data_dir() -> Path:
    override = next((os.environ[v] for v in ENV_VARS if os.environ.get(v)), None)
    if override:
        folder = Path(override)
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    portable = _new_or_old(app_root(), DATA_FOLDER_NAME, OLD_DATA_FOLDER_NAME)
    if _writable(portable):
        return portable
    fallback = _new_or_old(Path(os.environ.get("APPDATA", Path.home())), "AlexbedBRU", "AlexedBRU")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _new_or_old(parent: Path, new: str, old: str) -> Path:
    """The folder with the new name, unless only the old-named one exists."""
    if not (parent / new).exists() and (parent / old).is_dir():
        return parent / old
    return parent / new


def presets_dir() -> Path:
    folder = data_dir() / "presets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
