# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""The virtual data layer: RenameModel + painting delegates.

``RenameModel`` is a QAbstractTableModel that owns the file list. Per row it
exposes:
    source path, original name and extension, proposed name, status, and the
    file's metadata dictionary (loaded lazily via ``metadata(row)``).

Qt asks only for rows that are on screen, so 10k+ files cost almost nothing
to display. The model never computes names itself: the main window runs the
engine in a worker and pushes proposals back with ``set_proposals``.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from alexed_bru.core.models import FileItem, Proposal, Status
from alexed_bru.skills.metadata import MetadataStore
from alexed_bru.ui.theme import ADDED_COLOUR, GROUP_COLOURS, REMOVED_COLOUR, C

COL_INCLUDE, COL_STATUS, COL_ORIGINAL, COL_NEW, COL_FOLDER, COL_INFO = range(6)
HEADERS = ["", "Status", "Original name", "New name", "Folder", "Details"]

SPANS_ROLE = Qt.UserRole + 1     # list[(start, end, colour_index)]; -1 = diff colour
STATUS_ROLE = Qt.UserRole + 2
SORT_ROLE = Qt.UserRole + 3

STATUS_COLOURS = {Status.UNCHANGED: C.FAINT, Status.PENDING: C.ACCENT_HI, Status.WARNING: C.WARN,
                  Status.ERROR: C.ERROR, Status.SUCCESS: C.OK}

Highlighter = Callable[[str], list[tuple[int, int, int]]]


def _dot(colour: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 8, 8)
    p.end()
    return QIcon(pix)


def path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


class RenameModel(QAbstractTableModel):
    includeChanged = Signal()
    itemsChanged = Signal()
    manualChanged = Signal()  # a name was typed by hand or reset

    def __init__(self, store: MetadataStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.items: list[FileItem] = []
        self.proposals: list[Proposal] = []
        self.highlighter: Highlighter | None = None
        self._keys: set[str] = set()
        self._icons: dict[Status, QIcon] = {}
        self._bold = QFont()
        self._bold.setWeight(QFont.DemiBold)
        self._manual_font = QFont(self._bold)
        self._manual_font.setItalic(True)

    # ---- data management ----------------------------------------------------
    def add_paths(self, paths: Iterable[Path]) -> int:
        new = []
        for p in paths:
            key = path_key(p)
            if key not in self._keys:
                self._keys.add(key)
                new.append(FileItem(p))
        if new:
            first = len(self.items)
            self.beginInsertRows(QModelIndex(), first, first + len(new) - 1)
            self.items.extend(new)
            self.proposals.extend(Proposal(i.name) for i in new)
            self.endInsertRows()
            self.itemsChanged.emit()
        return len(new)

    def remove_rows(self, rows: Iterable[int]) -> None:
        drop = set(rows)
        if not drop:
            return
        self.beginResetModel()
        keep = [(i, p) for n, (i, p) in enumerate(zip(self.items, self.proposals)) if n not in drop]
        self.items = [i for i, _ in keep]
        self.proposals = [p for _, p in keep]
        self._keys = {path_key(i.path) for i in self.items}
        self.endResetModel()
        self.itemsChanged.emit()

    def clear(self) -> None:
        self.remove_rows(range(len(self.items)))

    def set_include(self, rows: Iterable[int], include: bool) -> None:
        for r in rows:
            self.items[r].include = include
        self._refresh_all()
        self.includeChanged.emit()

    def set_proposals(self, proposals: Sequence[Proposal]) -> None:
        if len(proposals) != len(self.items):
            return  # stale result for a different file list
        self.proposals = list(proposals)
        self._refresh_all()

    def set_highlighter(self, fn: Highlighter | None) -> None:
        self.highlighter = fn
        if self.items:
            self.dataChanged.emit(self.index(0, COL_ORIGINAL), self.index(len(self.items) - 1, COL_ORIGINAL))

    def relocate(self, mapping: dict[str, Path], mark_success: bool) -> None:
        """Point items at their new paths after a rename (or rollback).

        ``mapping`` is keyed by ``path_key(old_path)``.
        """
        for n, item in enumerate(self.items):
            new_path = mapping.get(path_key(item.path))
            if new_path is None:
                continue
            old_name = item.name
            item.path = new_path
            item.manual = None  # the file now has its new name; the typed one is used up
            if mark_success:
                self.proposals[n] = Proposal(new_path.name, Status.SUCCESS, ["Renamed"], previous=old_name)
        self._keys = {path_key(i.path) for i in self.items}
        self._refresh_all()

    def snapshot(self) -> list[FileItem]:
        """Thread-safe copy for background jobs."""
        return [FileItem(i.path, i.include, i.manual) for i in self.items]

    def reset_manual(self, rows: Iterable[int]) -> None:
        """Forget hand-typed names; the rules decide again."""
        changed = False
        for r in rows:
            if self.items[r].manual:
                self.items[r].manual = None
                changed = True
        if changed:
            self.manualChanged.emit()

    def manual_rows(self, rows: Iterable[int]) -> list[int]:
        return [r for r in rows if self.items[r].manual]

    def metadata(self, row: int) -> dict[str, dict]:
        """The file metadata dictionary for a row, grouped by namespace."""
        return self.store.all_for(self.items[row].path)

    def counts(self) -> dict[Status, int]:
        out = {s: 0 for s in Status}
        for item, prop in zip(self.items, self.proposals):
            if item.include:
                out[prop.status] += 1
        return out

    def _refresh_all(self) -> None:
        if self.items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.items) - 1, len(HEADERS) - 1))

    # ---- Qt model API ---------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        return None

    def flags(self, index):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_INCLUDE:
            base |= Qt.ItemIsUserCheckable
        elif index.column() == COL_NEW and self.items[index.row()].include:
            base |= Qt.ItemIsEditable  # double-click (or F2) to type a name by hand
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        item, prop = self.items[row], self.proposals[row]
        status = prop.status if item.include else Status.UNCHANGED
        original = prop.previous or item.name

        if role == Qt.DisplayRole:
            if col == COL_STATUS:
                return "Excluded" if not item.include else status.label
            if col == COL_ORIGINAL:
                return original
            if col == COL_NEW:
                return prop.new_name if item.include else item.name
            if col == COL_FOLDER:
                return str(item.folder)
            if col == COL_INFO:
                if not item.include:
                    return "Excluded"
                if item.manual and prop.status != Status.SUCCESS:
                    return "; ".join(["Edited by hand"] + prop.messages)
                return prop.message
        elif role == Qt.EditRole and col == COL_NEW:
            return prop.new_name
        elif role == Qt.CheckStateRole and col == COL_INCLUDE:
            return Qt.Checked if item.include else Qt.Unchecked
        elif role == Qt.DecorationRole and col == COL_NEW and item.include and item.manual:
            from alexed_bru.ui.icons import icon
            return icon("edit")
        elif role == Qt.DecorationRole and col == COL_STATUS:
            if status not in self._icons:
                self._icons[status] = _dot(STATUS_COLOURS[status])
            return self._icons[status]
        elif role == Qt.ForegroundRole:
            if not item.include:
                return QBrush(QColor(C.FAINT))
            if col == COL_NEW:
                return QBrush(QColor({Status.ERROR: C.ERROR, Status.WARNING: C.WARN,
                                      Status.SUCCESS: C.OK, Status.UNCHANGED: C.DIM}
                                     .get(status, C.TEXT)))
            if col in (COL_STATUS, COL_INFO):
                return QBrush(QColor(STATUS_COLOURS[status] if status != Status.PENDING else C.DIM))
            if col == COL_FOLDER:
                return QBrush(QColor(C.FAINT))
        elif role == Qt.FontRole and col == COL_NEW and item.include and item.manual:
            return self._manual_font
        elif role == Qt.FontRole and col == COL_NEW and status in (Status.PENDING, Status.WARNING):
            return self._bold
        elif role == Qt.ToolTipRole:
            if col == COL_INFO and prop.messages:
                return "\n".join(prop.messages)
            if col in (COL_ORIGINAL, COL_FOLDER):
                return str(item.path)
            if col == COL_NEW:
                if item.manual:
                    return (f"{prop.new_name}\n\nTyped by hand. Right-click → Reset to rule name, "
                            "or clear the text, to let the rules decide again.")
                return f"{prop.new_name}\n\nDouble-click to type a different name for this file."
        elif role == SPANS_ROLE:
            if not item.include:
                return None
            changing = status in (Status.PENDING, Status.WARNING, Status.ERROR)
            if col == COL_ORIGINAL:
                if self.highlighter:  # a RegEx rule is selected: show its matches
                    return self.highlighter(original)
                if changing:
                    return removed_spans(item.name, prop.new_name)
            if col == COL_NEW and changing:
                return diff_spans(item.name, prop.new_name)
        elif role == STATUS_ROLE:
            return status
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if index.column() == COL_NEW and role == Qt.EditRole:
            row = index.row()
            item, prop = self.items[row], self.proposals[row]
            text = str(value or "").strip()
            if text == (prop.new_name if not item.manual else item.manual):
                return False  # nothing changed
            # Empty text resets; otherwise the typed name wins over the rules.
            item.manual = text or None
            if text:
                self.proposals[row] = Proposal(text, Status.PENDING, [], manual=True)
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))
            self.manualChanged.emit()
            return True
        if index.column() == COL_INCLUDE and role == Qt.CheckStateRole:
            self.items[index.row()].include = Qt.CheckState(value) == Qt.Checked
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(HEADERS) - 1))
            self.includeChanged.emit()
            return True
        return False

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        """Sorting reorders the real list, so counters follow what you see."""
        keyfuncs = {
            COL_INCLUDE: lambda ip: not ip[0].include,
            COL_STATUS: lambda ip: -int(ip[1].status),
            COL_ORIGINAL: lambda ip: natural_name(ip[0].name),
            COL_NEW: lambda ip: natural_name(ip[1].new_name),
            COL_FOLDER: lambda ip: (_natural(str(ip[0].folder)), natural_name(ip[0].name)),
            COL_INFO: lambda ip: ip[1].message,
        }
        key = keyfuncs.get(column)
        if key is None:
            return
        self.layoutAboutToBeChanged.emit()
        pairs = sorted(zip(self.items, self.proposals), key=key, reverse=order == Qt.DescendingOrder)
        self.items = [i for i, _ in pairs]
        self.proposals = [p for _, p in pairs]
        self.layoutChanged.emit()
        self.itemsChanged.emit()


def _natural(text: str):
    """Natural sort: 'Track 2' before 'Track 10'."""
    import re
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def natural_name(name: str):
    """Natural sort of a file name by stem, then extension, so 'Photo.png' comes
    before 'Photo 2.png' (comparing whole names would put ' ' before '.')."""
    from alexed_bru.core.models import split_name
    stem, ext = split_name(name)
    return (_natural(stem), _natural(ext))


ADDED, REMOVED = -1, -2  # span colour indexes for the diff (>= 0 are regex groups)


def _diff(old: str, new: str, side: str) -> list[tuple[int, int, int]]:
    if old == new:
        return []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    if side == "new":
        raw = [(j1, j2) for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
               if tag in ("replace", "insert") and j2 > j1]
        text, kind = new, ADDED
    else:
        raw = [(i1, i2) for tag, i1, i2, _j1, _j2 in matcher.get_opcodes()
               if tag in ("replace", "delete") and i2 > i1]
        text, kind = old, REMOVED
    merged: list[list[int]] = []
    for start, end in raw:  # merge spans split by tiny coincidental matches
        if merged and start - merged[-1][1] <= 3:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    if sum(e - s for s, e in merged) > 0.7 * len(text):
        merged = [[merged[0][0], merged[-1][1]]]  # mostly new: one clear block, not confetti
    return [(s, e, kind) for s, e in merged]


def diff_spans(old: str, new: str) -> list[tuple[int, int, int]]:
    """Ranges in ``new`` that were added or changed (painted as ADDED)."""
    return _diff(old, new, "new")


def removed_spans(old: str, new: str) -> list[tuple[int, int, int]]:
    """Ranges in ``old`` that will be removed or replaced (painted as REMOVED)."""
    return _diff(old, new, "old")


# ==========================================================================
class FilterProxy(QSortFilterProxyModel):
    """Text + status filtering. Sorting is delegated to the source model."""

    MODES = [("all", "All files"), ("changed", "Will change"), ("problems", "Problems"),
             ("unchanged", "Unchanged"), ("excluded", "Excluded")]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._mode = "all"

    def set_filter(self, text: str, mode: str) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.10
            self.beginFilterChange()
            self._text, self._mode = text.casefold(), mode
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self._text, self._mode = text.casefold(), mode
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        model: RenameModel = self.sourceModel()
        item, prop = model.items[row], model.proposals[row]
        if self._text and self._text not in item.name.casefold() and self._text not in prop.new_name.casefold():
            return False
        status = prop.status
        if self._mode == "changed":
            return item.include and status in (Status.PENDING, Status.WARNING, Status.SUCCESS)
        if self._mode == "problems":
            return item.include and status in (Status.WARNING, Status.ERROR)
        if self._mode == "unchanged":
            return item.include and status == Status.UNCHANGED
        if self._mode == "excluded":
            return not item.include
        return True

    def sort(self, column, order=Qt.AscendingOrder):
        self.sourceModel().sort(column, order)


# ==========================================================================
class HighlightDelegate(QStyledItemDelegate):
    """Paints text with coloured spans (regex groups or diff ranges)."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        spans = index.data(SPANS_ROLE)
        if not spans:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        rect: QRect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget).adjusted(3, 0, -3, 0)

        painter.save()
        painter.setClipRect(rect)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(opt.font)
        fm = painter.fontMetrics()
        base_colour = opt.palette.color(opt.palette.ColorRole.Text)
        fg = index.data(Qt.ForegroundRole)
        if isinstance(fg, QBrush):
            base_colour = fg.color()
        y_text = rect.top() + (rect.height() + fm.ascent() - fm.descent()) // 2
        x = rect.left()
        pos = 0
        for start, end, colour_idx in sorted(spans):
            start, end = max(start, pos), min(end, len(text))
            if start >= end:
                continue
            x = self._run(painter, fm, text[pos:start], x, y_text, base_colour)
            if colour_idx == ADDED:
                colour, alpha, ink = QColor(ADDED_COLOUR), 80, QColor("#FFFFFF")
            elif colour_idx == REMOVED:
                colour, alpha, ink = QColor(REMOVED_COLOUR), 45, QColor(REMOVED_COLOUR).lighter(115)
            else:
                colour = QColor(GROUP_COLOURS[colour_idx % len(GROUP_COLOURS)])
                alpha, ink = 55, QColor("#FFFFFF")
            seg = text[start:end]
            w = fm.horizontalAdvance(seg)
            bg = QColor(colour)
            bg.setAlpha(alpha)
            top = rect.center().y() - fm.height() // 2 - 1
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(x - 1, top, w + 2, fm.height() + 2, 3, 3)
            if colour_idx == ADDED:  # a solid underline makes additions pop at a glance
                painter.setBrush(colour)
                painter.drawRect(x - 1, top + fm.height(), w + 2, 2)
            x_start = x
            x = self._run(painter, fm, seg, x, y_text, ink)
            if colour_idx == REMOVED:  # strike through what will be removed
                painter.setPen(ink)
                mid = y_text - fm.strikeOutPos()
                painter.drawLine(x_start, mid, x, mid)
            pos = end
        self._run(painter, fm, text[pos:], x, y_text, base_colour)
        painter.restore()

    @staticmethod
    def _run(painter, fm, text, x, y, colour) -> int:
        if text:
            painter.setPen(colour)
            painter.drawText(x, y, text)
        return x + fm.horizontalAdvance(text)
