# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dark theme: palette, stylesheet and native Windows 11 title bar."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from alexed_bru.paths import resource_path


class C:
    BG = "#0B0D1A"
    SURFACE = "#11142A"
    SURFACE_2 = "#171B35"
    SURFACE_3 = "#1F2445"
    BORDER = "#262B4D"
    BORDER_HI = "#3A4170"
    TEXT = "#E2E8F0"
    DIM = "#8A93B5"
    FAINT = "#5A6288"
    ACCENT = "#6366F1"
    ACCENT_HI = "#818CF8"
    CYAN = "#22D3EE"
    VIOLET = "#C084FC"
    OK = "#34D399"
    WARN = "#FBBF24"
    ERROR = "#F87171"


# Highlight colours for regex groups: full match, then group 1, 2, ...
GROUP_COLOURS = ["#6366F1", "#22D3EE", "#C084FC", "#34D399", "#FBBF24", "#F472B6", "#60A5FA"]
# Preview diff: what a rename adds (new name) and removes (original name).
ADDED_COLOUR = "#22D3EE"
REMOVED_COLOUR = "#FB7185"

QSS = f"""
* {{ outline: 0; }}
QMainWindow, QDialog {{ background: {C.BG}; }}
QWidget {{ color: {C.TEXT}; font-size: 10pt; }}
QToolTip {{ background: {C.SURFACE_3}; color: {C.TEXT}; border: 1px solid {C.BORDER_HI};
           padding: 6px 8px; border-radius: 6px; }}

#Header {{ background: {C.SURFACE}; border-bottom: 1px solid {C.BORDER}; }}
#AppTitle {{ font-size: 13pt; font-weight: 700; color: {C.TEXT}; }}
#AppSubtitle {{ font-size: 8.5pt; letter-spacing: 2px; color: {C.DIM}; }}
#Panel {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 12px; }}
#SectionTitle {{ font-size: 8.5pt; font-weight: 700; letter-spacing: 1.5px; color: {C.DIM}; }}
#RuleTitle {{ font-size: 12pt; font-weight: 600; }}
#Dim {{ color: {C.DIM}; }}
#Faint {{ color: {C.FAINT}; }}
#ErrorText {{ color: {C.ERROR}; }}
#Counts {{ color: {C.DIM}; }}
#DropHint {{ color: {C.FAINT}; font-size: 12pt; }}

QPushButton, QToolButton {{
    background: {C.SURFACE_2}; border: 1px solid {C.BORDER}; border-radius: 8px;
    padding: 6px 12px; color: {C.TEXT};
}}
QPushButton:hover, QToolButton:hover {{ background: {C.SURFACE_3}; border-color: {C.BORDER_HI}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {C.BORDER}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {C.FAINT}; background: {C.SURFACE}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C.ACCENT}, stop:1 #8B5CF6);
    border: none; font-weight: 700; padding: 7px 22px; color: white;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C.ACCENT_HI}, stop:1 #A78BFA);
}}
QPushButton#Primary:disabled {{ background: {C.SURFACE_3}; color: {C.FAINT}; }}
QToolButton#Flat, QPushButton#Flat {{ background: transparent; border: none; padding: 4px 6px; }}
QToolButton#Flat:hover, QPushButton#Flat:hover {{ background: {C.SURFACE_3}; }}
QPushButton#Segment {{ padding: 5px 12px; border-radius: 7px; color: {C.DIM}; }}
QPushButton#Segment:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: white; font-weight: 600; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 7px;
    padding: 5px 8px; selection-background-color: {C.ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {C.ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {C.ERROR}; }}
QLineEdit#Mono {{ font-family: "MONO_FONT"; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {C.SURFACE_2}; border: 1px solid {C.BORDER_HI};
    selection-background-color: {C.ACCENT}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {C.BORDER_HI}; background: {C.BG}; }}
QCheckBox::indicator:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT};
    image: url(CHECK_URL); }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 9px; margin: 2px 0; }}
QListWidget::item:selected {{ background: {C.SURFACE_3}; }}
QListWidget::item:hover:!selected {{ background: {C.SURFACE_2}; }}

QTableView {{
    background: {C.SURFACE}; alternate-background-color: #13172F; border: none;
    gridline-color: transparent; selection-background-color: #2A2F5C; selection-color: {C.TEXT};
}}
QTableView::item {{ padding: 0 6px; border: none; }}
QHeaderView::section {{
    background: {C.SURFACE}; color: {C.DIM}; border: none; border-bottom: 1px solid {C.BORDER};
    padding: 8px 6px; font-weight: 600; font-size: 8.5pt;
}}
QHeaderView::section:hover {{ color: {C.TEXT}; }}
QTableCornerButton::section {{ background: {C.SURFACE}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {C.BORDER_HI}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {C.FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; height: 0; width: 0; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QMenu {{ background: {C.SURFACE_2}; border: 1px solid {C.BORDER_HI}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {C.ACCENT}; }}
QMenu::item:disabled {{ color: {C.FAINT}; }}
QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 5px 8px; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QStatusBar {{ background: {C.SURFACE}; border-top: 1px solid {C.BORDER}; color: {C.DIM}; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{ background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: 5px; height: 10px;
    text-align: center; font-size: 7pt; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C.CYAN}, stop:1 {C.ACCENT}); }}
QTreeWidget {{ background: transparent; border: none; }}
QTreeWidget::item {{ padding: 2px; }}
QMessageBox {{ background: {C.SURFACE}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: C.BG, QPalette.WindowText: C.TEXT, QPalette.Base: C.SURFACE,
        QPalette.AlternateBase: C.SURFACE_2, QPalette.Text: C.TEXT, QPalette.Button: C.SURFACE_2,
        QPalette.ButtonText: C.TEXT, QPalette.Highlight: C.ACCENT, QPalette.HighlightedText: "#FFFFFF",
        QPalette.ToolTipBase: C.SURFACE_3, QPalette.ToolTipText: C.TEXT, QPalette.PlaceholderText: C.FAINT,
        QPalette.Link: C.CYAN, QPalette.Mid: C.BORDER, QPalette.Dark: C.BG, QPalette.Light: C.BORDER_HI,
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(C.FAINT))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(C.FAINT))
    app.setPalette(pal)
    # One family name only. Each extra fallback name makes Qt enumerate every
    # installed font, which takes seconds on PCs with thousands of fonts.
    font = QFont(_pick_font(UI_FONTS))
    font.setPointSizeF(10)
    app.setFont(font)
    check = resource_path("assets/ui/check.svg").as_posix()
    app.setStyleSheet(QSS.replace("CHECK_URL", check).replace("MONO_FONT", _pick_font(MONO_FONTS)))


# (family, font file) in order of preference; the last entry is the fallback.
UI_FONTS = [("Segoe UI Variable Text", "SegUIVar.ttf"), ("Segoe UI", "segoeui.ttf")]
MONO_FONTS = [("Cascadia Mono", "CascadiaMono.ttf"), ("Consolas", "consola.ttf")]


def _pick_font(candidates: list[tuple[str, str]]) -> str:
    """Choose a family by checking font files, without asking Qt's font database."""
    if sys.platform == "win32":
        folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
        for family, filename in candidates:
            if any((f / filename).exists() for f in folders):
                return family
    return candidates[-1][0]


def dark_title_bar(widget: QWidget) -> None:
    """Ask DWM for a dark caption on Windows 10/11 (no registry involved)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))  # immersive dark
        caption = ctypes.c_int(0x002A1411)  # COLORREF of #11142A (0x00BBGGRR)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
    except Exception:  # noqa: BLE001  (purely cosmetic)
        pass
