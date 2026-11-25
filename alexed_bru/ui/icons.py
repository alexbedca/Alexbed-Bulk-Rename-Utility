# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small line icons drawn from inline SVG.

Buttons use these instead of Unicode symbols such as an undo arrow. If the UI
font lacks a symbol, Qt searches every installed font for it, which can stall
startup for many seconds on PCs with thousands of fonts.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QIcon, QPixmap

from alexed_bru.ui.theme import C

# 16x16 viewBox path data, stroked (no fill).
_PATHS = {
    "undo": "M5.5 3.5 2.5 6.5l3 3M2.5 6.5H10a3.5 3.5 0 0 1 0 7H6",
    "redo": "M10.5 3.5l3 3-3 3M13.5 6.5H6a3.5 3.5 0 0 0 0 7h4",
    "up": "M8 13V3M4 7l4-4 4 4",
    "down": "M8 3v10M4 9l4 4 4-4",
    "duplicate": "M5.5 5.5h8v8h-8zM10.5 5.5v-3h-8v8h3",
    "close": "M4 4l8 8M12 4l-8 8",
    "chevron": "M4.5 6.5 8 10l3.5-3.5",
    "edit": "M10.5 2.5l3 3-7.5 7.5H3v-3zM9 4l3 3",
    "folder": "M1.5 4V12.5a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1H8L6.5 3h-4a1 1 0 0 0-1 1z",
    # three dots: tiny rings that the 1.6 stroke fills in
    "more": ("M1.8 8a1.2 1.2 0 1 0 2.4 0a1.2 1.2 0 1 0-2.4 0zM6.8 8a1.2 1.2 0 1 0 2.4 0a1.2 1.2 0 1 0-2.4 0z"
             "M11.8 8a1.2 1.2 0 1 0 2.4 0a1.2 1.2 0 1 0-2.4 0z"),
}


def _pixmap(name: str, colour: str, size: int) -> QPixmap:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="{size}" height="{size}">'
           f'<path d="{_PATHS[name]}" fill="none" stroke="{colour}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    pix = QPixmap()
    pix.loadFromData(svg.encode(), "SVG")
    return pix


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    """A themed icon with normal and disabled states, crisp at 100-200% scaling."""
    ic = QIcon()
    for size in (16, 24, 32):
        ic.addPixmap(_pixmap(name, C.TEXT, size), QIcon.Normal)
        ic.addPixmap(_pixmap(name, C.FAINT, size), QIcon.Disabled)
    return ic
