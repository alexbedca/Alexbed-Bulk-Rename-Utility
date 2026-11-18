# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window: rules on the left, live preview grid on the right."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QProgressDialog,
                               QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableView,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from alexed_bru import APP_NAME
from alexed_bru.core import presets
from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import Batch, History
from alexed_bru.core.models import Status, split_name
from alexed_bru.core.tags import format_value
from alexed_bru.paths import data_dir, presets_dir, resource_path
from alexed_bru.skills.base import Rule
from alexed_bru.skills.metadata import PROVIDERS, MetadataStore
from alexed_bru.skills.rules import RegexRule, ReplaceRule, compile_regex
from alexed_bru.ui.preview_model import (COL_FOLDER, COL_INCLUDE, COL_INFO, COL_NEW, COL_ORIGINAL,
                                         COL_STATUS, FilterProxy, HighlightDelegate, RenameModel,
                                         natural_name, path_key)
from alexed_bru.ui.icons import icon
from alexed_bru.ui.rule_editor import RuleEditor, RuleRow, RuleStack, menu_text, rules_menu
from alexed_bru.ui.theme import ADDED_COLOUR, REMOVED_COLOUR, C, dark_title_bar
from alexed_bru.ui.workers import Job, JobRunner

SKIP_PREFIX = ".~abru-"  # our own temp files, never list them
DUPLICATES_FOLDER = "_Duplicates"  # same as core.duplicates (not imported: keeps startup lean)


def scan(paths: list[Path], recursive: bool, cancelled) -> list[Path]:
    """Expand dropped/selected paths into a naturally sorted file list."""
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            if recursive:
                for root, dirs, files in os.walk(p):
                    if cancelled():
                        return out
                    # copies set aside by Find duplicates stay out of later scans
                    dirs[:] = sorted((d for d in dirs if d != DUPLICATES_FOLDER), key=_natural)
                    out.extend(Path(root) / f for f in sorted(files, key=natural_name))
            else:
                out.extend(sorted((c for c in p.iterdir() if c.is_file()), key=lambda c: natural_name(c.name)))
    return [p for p in out if not p.name.startswith(SKIP_PREFIX)]


def _rgba(hex_colour: str, alpha: float) -> str:
    """'#RRGGBB' -> 'rgba(r,g,b,a)' (Qt reads 8-digit hex as #AARRGGBB)."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _natural(text: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def panel() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Panel")
    return frame


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


# ==========================================================================
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 680)
        self.store = MetadataStore()
        self.history = History.load(data_dir() / "history.json")
        self.engine = RenameEngine([], self.store, self.history)
        self.rules: list[Rule] = []
        self.model = RenameModel(self.store, self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.runner = JobRunner(self)
        self.settings = self._load_settings()

        self._gen = 0
        self._preview_job: Job | None = None
        self._apply_when_ready = False
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._last_state = "[]"

        self._preview_timer = QTimer(self, singleShot=True, interval=90, timeout=self._start_preview)
        self._snapshot_timer = QTimer(self, singleShot=True, interval=700, timeout=self._commit_snapshot)

        self._build_ui()
        self._build_shortcuts()
        self.model.itemsChanged.connect(self._on_items_changed)
        self.model.includeChanged.connect(self.schedule_preview)
        self.model.manualChanged.connect(self.schedule_preview)
        self.setAcceptDrops(True)
        self._restore_session()

    # ======================================================================
    # UI construction
    # ======================================================================
    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_left())
        body.addWidget(self._build_right())
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([380, 1000])
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 12)
        wl.addWidget(body)
        outer.addWidget(wrap, 1)
        self.setCentralWidget(root)

        self.status_text = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.status_text, 1)
        self.statusBar().addPermanentWidget(self.progress)
        data_label = QLabel(f"Data: {data_dir()}")
        data_label.setObjectName("Faint")
        self.statusBar().addPermanentWidget(data_label)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)

        logo = QLabel()
        pix = QPixmap(str(resource_path("assets/branding/png/logo-mark-64.png")))
        logo.setPixmap(pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t1 = QLabel(f"<span style='color:{C.CYAN}'>Alex</span><span style='color:{C.VIOLET}'>ed</span>")
        t1.setObjectName("AppTitle")
        t2 = QLabel("BULK RENAME UTILITY")
        t2.setObjectName("AppSubtitle")
        titles.addWidget(t1)
        titles.addWidget(t2)
        lay.addWidget(logo)
        lay.addSpacing(4)
        lay.addLayout(titles)
        lay.addSpacing(22)

        def button(text, tip, slot, name=None) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            if name:
                b.setObjectName(name)
            lay.addWidget(b)
            return b

        button("+  Files", "Add files (Ctrl+O)", self.add_files_dialog)
        button("+  Folder", "Add a folder (Ctrl+Shift+O)", self.add_folder_dialog)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(self.settings.get("recursive", True))
        lay.addWidget(self.recursive)
        button("Clear", "Remove all files from the list", self.clear_files, "Flat")
        lay.addStretch(1)

        self.undo_btn = button("", "Undo rule change (Ctrl+Z)", self.undo_rules, "Flat")
        self.redo_btn = button("", "Redo rule change (Ctrl+Y)", self.redo_rules, "Flat")
        for b, name in ((self.undo_btn, "undo"), (self.redo_btn, "redo")):
            b.setIcon(icon(name))
            b.setIconSize(QSize(18, 18))
            b.setFixedWidth(34)
        presets_btn = QToolButton()
        presets_btn.setText("Presets")
        presets_btn.setIcon(icon("chevron"))
        presets_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        presets_btn.setLayoutDirection(Qt.RightToLeft)  # chevron after the text
        presets_btn.setPopupMode(QToolButton.InstantPopup)
        self.presets_menu = QMenu(presets_btn)
        self.presets_menu.setLayoutDirection(Qt.LeftToRight)  # the button is RTL only for its arrow
        self.presets_menu.aboutToShow.connect(self._fill_presets_menu)
        presets_btn.setMenu(self.presets_menu)
        lay.addWidget(presets_btn)
        button("Duplicates", "Find files in the list with identical content and set the extra "
               "copies aside", self.find_duplicates)
        button("History", "Applied renames: undo or redo past batches (Ctrl+H)", self.show_history)
        more = QToolButton()
        more.setIcon(icon("more"))
        more.setIconSize(QSize(18, 18))
        more.setToolTip("More options")
        more.setPopupMode(QToolButton.InstantPopup)
        # the theme's wide padding would squeeze the icon in a narrow button
        more.setStyleSheet("QToolButton { padding: 4px 6px; } QToolButton::menu-indicator { image: none; width: 0; }")
        more.setFixedWidth(38)
        self.more_menu = QMenu(more)
        self.sendto_action = self.more_menu.addAction("Add to Windows “Send To” menu")
        self.sendto_action.setCheckable(True)
        self.sendto_action.setToolTip("Right-click files in Explorer → Send to → Alexed Bulk Rename.\n"
                                      "Adds one shortcut to your own Send To folder; no admin rights.")
        self.sendto_action.triggered.connect(self.toggle_sendto)
        self.more_menu.addAction("Open data folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(data_dir()))))
        self.more_menu.setToolTipsVisible(True)
        self.more_menu.aboutToShow.connect(self._sync_more_menu)
        more.setMenu(self.more_menu)
        lay.addWidget(more)
        lay.addSpacing(8)
        self.apply_btn = button("Rename files", "Apply the pending renames (Ctrl+Enter)", self.apply, "Primary")
        self.apply_btn.setEnabled(False)
        self._update_undo_buttons()
        return header

    def _build_left(self) -> QWidget:
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        stack_panel = panel()
        sl = QVBoxLayout(stack_panel)
        sl.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.addWidget(section_title("Rule stack"))
        top.addStretch(1)
        add = QToolButton()
        add.setText("+  Add rule")
        add.setPopupMode(QToolButton.InstantPopup)
        add.setMenu(rules_menu(add, self.add_rule))
        add.setStyleSheet(f"background:{C.ACCENT}; border:none; font-weight:600;")
        top.addWidget(add)
        sl.addLayout(top)

        self.stack = RuleStack()
        self.stack.currentRowChanged.connect(self._on_rule_selected)
        self.stack.orderChanged.connect(self._on_rules_reordered)
        self.stack.enabledChanged.connect(self._on_rule_toggled)
        self.stack.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stack.customContextMenuRequested.connect(self._rule_context_menu)
        sl.addWidget(self.stack, 1)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        for name, tip, slot in (("up", "Move up", lambda: self.move_rule(-1)),
                                ("down", "Move down", lambda: self.move_rule(1)),
                                ("duplicate", "Duplicate", self.duplicate_rule),
                                ("close", "Delete rule", self.delete_rule)):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setToolTip(tip)
            b.setObjectName("Flat")
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        clear = QToolButton()
        clear.setText("Clear all")
        clear.setObjectName("Flat")
        clear.clicked.connect(self.clear_rules)
        tools.addWidget(clear)
        sl.addLayout(tools)

        editor_panel = panel()
        el = QVBoxLayout(editor_panel)
        el.setContentsMargins(14, 12, 14, 12)
        el.addWidget(section_title("Rule settings"))
        self.editor = RuleEditor()
        self.editor.sample_names = self._sample_names
        self.editor.changed.connect(self._on_rule_edited)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.editor)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        el.addWidget(scroll, 1)

        split.addWidget(stack_panel)
        split.addWidget(editor_panel)
        split.setSizes([290, 420])  # room for ~4 rules; settings get the larger share
        split.setMinimumWidth(340)
        return split

    def _build_right(self) -> QWidget:
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(True)

        grid_panel = panel()
        gl = QVBoxLayout(grid_panel)
        gl.setContentsMargins(14, 12, 14, 8)
        bar = QHBoxLayout()
        bar.addWidget(section_title("Preview"))
        bar.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.filter_mode = QComboBox()
        for key, label in FilterProxy.MODES:
            self.filter_mode.addItem(label, key)
        self.search.textChanged.connect(self._apply_filter)
        self.filter_mode.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.search)
        bar.addWidget(self.filter_mode)
        bar.addSpacing(10)
        self.auto_number = QCheckBox("Auto-number duplicate names")
        self.auto_number.setToolTip("When two files would get the same name, number them instead of "
                                    "skipping them:\nphoto.jpg, photo (1).jpg, photo (2).jpg")
        self.auto_number.setChecked(bool(self.settings.get("auto_number", False)))
        self.auto_number.toggled.connect(self.schedule_preview)
        bar.addWidget(self.auto_number)
        bar.addStretch(1)
        # Key for the preview highlighting, shown while there is something to rename.
        self.legend = QLabel(
            f"<span style='background:{_rgba(ADDED_COLOUR, 0.35)}; color:white; "
            f"text-decoration:underline'>&nbsp;added&nbsp;</span>&nbsp;&nbsp;"
            f"<span style='background:{_rgba(REMOVED_COLOUR, 0.2)}; color:{REMOVED_COLOUR}; "
            f"text-decoration:line-through'>&nbsp;removed&nbsp;</span>")
        self.legend.setToolTip("New name: added or changed characters.\n"
                               "Original name: characters the rename removes.")
        self.legend.setStyleSheet("font-size:8.5pt; margin-right:14px;")
        self.legend.hide()
        bar.addWidget(self.legend)
        self.counts = QLabel()
        self.counts.setObjectName("Counts")
        bar.addWidget(self.counts)
        gl.addLayout(bar)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(HighlightDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, width in ((COL_INCLUDE, 34), (COL_STATUS, 104), (COL_ORIGINAL, 320),
                           (COL_NEW, 340), (COL_FOLDER, 220), (COL_INFO, 200)):
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(COL_INCLUDE, QHeaderView.Fixed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.selectionModel().currentRowChanged.connect(self._show_details)

        self.drop_hint = QLabel("Drop files or folders here\n\n"
                                "or use  + Files  /  + Folder  above.\n"
                                "Nothing on disk changes until you press  Rename files.")
        self.drop_hint.setObjectName("DropHint")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.grid_stack = QStackedWidget()
        self.grid_stack.addWidget(self.drop_hint)
        self.grid_stack.addWidget(self.table)
        gl.addWidget(self.grid_stack, 1)

        details_panel = panel()
        dl = QVBoxLayout(details_panel)
        dl.setContentsMargins(14, 10, 14, 10)
        dtop = QHBoxLayout()
        dtop.addWidget(section_title("File metadata"))
        hint = QLabel("double-click a value to copy its tag")
        hint.setObjectName("Faint")
        dtop.addStretch(1)
        dtop.addWidget(hint)
        dl.addLayout(dtop)
        self.details = QTreeWidget()
        self.details.setHeaderHidden(True)
        self.details.setColumnCount(3)
        self.details.setRootIsDecorated(True)
        self.details.itemDoubleClicked.connect(self._copy_tag)
        dl.addWidget(self.details, 1)

        split.addWidget(grid_panel)
        split.addWidget(details_panel)
        split.setSizes([620, 170])
        return split

    def _build_shortcuts(self) -> None:
        def sc(seq, slot, widget=None):
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.triggered.connect(slot)
            if widget is not None:
                act.setShortcutContext(Qt.WidgetWithChildrenShortcut)
                widget.addAction(act)
            else:
                self.addAction(act)

        sc("Ctrl+O", self.add_files_dialog)
        sc("Ctrl+Shift+O", self.add_folder_dialog)
        sc("Ctrl+Return", self.apply)
        sc("Ctrl+Z", self.undo_rules)
        sc("Ctrl+Y", self.redo_rules)
        sc("Ctrl+Shift+Z", self.redo_rules)
        sc("Ctrl+S", self.save_preset)
        sc("Ctrl+H", self.show_history)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Delete", self.remove_selected_files, self.table)
        sc("Delete", self.delete_rule, self.stack)

    # ======================================================================
    # Files
    # ======================================================================
    def add_files_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", self.settings.get("last_dir", ""))
        if files:
            self.settings["last_dir"] = str(Path(files[0]).parent)
            self.add_paths([Path(f) for f in files])

    def add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder", self.settings.get("last_dir", ""))
        if folder:
            self.settings["last_dir"] = folder
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> None:
        recursive = self.recursive.isChecked()
        self._busy("Scanning…")
        job = Job(0, lambda _p, cancelled: scan(paths, recursive, cancelled))
        job.signals.result.connect(lambda _g, found: self._on_scanned(found))
        job.signals.error.connect(lambda _g, tb: self._job_error("Scanning failed", tb))
        self.runner.start(job)

    def _on_scanned(self, found: list[Path]) -> None:
        added = self.model.add_paths(found)
        skipped = len(found) - added
        self._idle(f"Added {added:,} file(s)" + (f" · {skipped:,} already listed" if skipped else ""))

    def clear_files(self) -> None:
        self.model.clear()
        self.store.invalidate()

    def remove_selected_files(self) -> None:
        self.model.remove_rows(self._selected_rows())

    def _sample_names(self) -> list[str]:
        """Names for RegEx 'From example': selected files first, then the list order."""
        items = self.model.items
        selected = [items[r].name for r in self._selected_rows() if r < len(items)] \
            if hasattr(self, "table") else []
        return list(dict.fromkeys(selected + [i.name for i in items]))

    def forget_files(self, paths: list[Path]) -> None:
        """Drop files from the list (they were moved away or recycled)."""
        gone = {path_key(p) for p in paths}
        self.model.remove_rows(n for n, item in enumerate(self.model.items) if path_key(item.path) in gone)
        self.store.invalidate(paths)

    def find_duplicates(self) -> None:
        if not self.model.items:
            QMessageBox.information(self, APP_NAME, "Add some files or a folder first.")
            return
        from alexed_bru.ui.duplicates_dialog import DuplicatesDialog  # loaded on demand: startup cost
        DuplicatesDialog(self, [i.path for i in self.model.items]).exec()

    def _selected_rows(self) -> list[int]:
        return sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})

    def _on_items_changed(self) -> None:
        self.grid_stack.setCurrentIndex(1 if self.model.items else 0)
        self.schedule_preview()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)

    # ======================================================================
    # Rules
    # ======================================================================
    def add_rule(self, cls: type[Rule]) -> None:
        self.rules.append(cls())
        self._rules_structure_changed(select=len(self.rules) - 1)

    def current_rule_index(self) -> int:
        return self.stack.currentRow()

    def move_rule(self, delta: int) -> None:
        i = self.current_rule_index()
        j = i + delta
        if 0 <= i < len(self.rules) and 0 <= j < len(self.rules):
            self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
            self._rules_structure_changed(select=j)

    def duplicate_rule(self) -> None:
        i = self.current_rule_index()
        if 0 <= i < len(self.rules):
            self.rules.insert(i + 1, self.rules[i].clone())
            self._rules_structure_changed(select=i + 1)

    def delete_rule(self) -> None:
        i = self.current_rule_index()
        if 0 <= i < len(self.rules):
            del self.rules[i]
            self._rules_structure_changed(select=min(i, len(self.rules) - 1))

    def clear_rules(self) -> None:
        if self.rules:
            self.rules.clear()
            self._rules_structure_changed(select=None)

    def set_rules(self, rules: list[Rule], record: bool = True) -> None:
        self.rules = rules
        self._rules_structure_changed(select=0 if rules else None, record=record)

    def _rules_structure_changed(self, select: int | None, record: bool = True) -> None:
        self.stack.populate(self.rules, select)
        if select is None or not self.rules:
            self.editor.set_rule(None)
        if record:
            self._commit_snapshot()
        self.schedule_preview()

    def _on_rules_reordered(self, order: list[int]) -> None:
        current = self.stack.currentRow()
        self.rules = [self.rules[i] for i in order]
        QTimer.singleShot(0, lambda: self._rules_structure_changed(select=current))

    def _on_rule_toggled(self, index: int, enabled: bool) -> None:
        self.rules[index].enabled = enabled
        QTimer.singleShot(0, lambda: self._rules_structure_changed(select=index))

    def _on_rule_selected(self, row: int) -> None:
        self.editor.set_rule(self.rules[row] if 0 <= row < len(self.rules) else None)
        self._update_highlighter()

    def _on_rule_edited(self) -> None:
        row = self.current_rule_index()
        widget = self.stack.itemWidget(self.stack.item(row)) if row >= 0 else None
        if widget is not None:  # refresh the summary line without rebuilding the editor
            item = self.stack.item(row)
            self.stack.setItemWidget(item, RuleRow(row + 1, self.rules[row]))
            new_row = self.stack.itemWidget(item)
            new_row.toggled.connect(lambda on, i=row: self._on_rule_toggled(i, on))
        self._update_highlighter()
        self._snapshot_timer.start()
        self.schedule_preview()

    def _rule_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addMenu(rules_menu(menu, self.add_rule)).setText("Add rule")
        if self.current_rule_index() >= 0:
            menu.addAction("Duplicate", self.duplicate_rule)
            menu.addAction("Delete", self.delete_rule)
        menu.exec(self.stack.mapToGlobal(pos))

    def _update_highlighter(self) -> None:
        """Live-highlight what the selected rule matches in the Original column."""
        row = self.current_rule_index()
        rule = self.rules[row] if 0 <= row < len(self.rules) else None
        rx = None
        if isinstance(rule, RegexRule) and rule.enabled:
            rx = rule.regex()
        elif isinstance(rule, ReplaceRule) and rule.enabled and rule.find:
            rx = compile_regex(re.escape(rule.find), not rule.case_sensitive)
        if rx is None:
            self.model.set_highlighter(None)
            return
        target = rule.target

        def spans(name: str) -> list[tuple[int, int, int]]:
            stem, ext = split_name(name)
            text, offset = {"name": (stem, 0), "ext": (ext, len(stem) + 1)}.get(target, (name, 0))
            colours: list[int | None] = [None] * len(text)
            for m in rx.finditer(text):
                for i in range(m.start(), m.end()):
                    colours[i] = 0
                for g in range(1, (rx.groups or 0) + 1):
                    if m.start(g) >= 0:
                        for i in range(m.start(g), m.end(g)):
                            colours[i] = g
            out, start = [], None
            for i, c in enumerate(colours + [None]):
                if start is not None and (i == len(colours) or c != colours[start]):
                    out.append((start + offset, i + offset, colours[start]))
                    start = None
                if start is None and i < len(colours) and c is not None:
                    start = i
            return out

        self.model.set_highlighter(spans)

    # ---- rule-edit undo / redo ---------------------------------------------
    def _state(self) -> str:
        return json.dumps([r.to_dict() for r in self.rules], sort_keys=True)

    def _commit_snapshot(self) -> None:
        self._snapshot_timer.stop()
        state = self._state()
        if state != self._last_state:
            self._undo.append(self._last_state)
            del self._undo[:-200]
            self._last_state = state
            self._redo.clear()
        self._update_undo_buttons()

    def _restore_state(self, state: str) -> None:
        self._last_state = state
        current = self.current_rule_index()
        self.rules = [Rule.from_dict(d) for d in json.loads(state)]
        self.stack.populate(self.rules, min(max(current, 0), len(self.rules) - 1) if self.rules else None)
        if not self.rules:
            self.editor.set_rule(None)
        self._update_undo_buttons()
        self.schedule_preview()

    def undo_rules(self) -> None:
        if isinstance(QGuiApplication.focusObject(), QLineEdit):
            fo = QGuiApplication.focusObject()
            if fo.isUndoAvailable():  # let text fields undo their own typing first
                fo.undo()
                return
        self._commit_snapshot()
        if self._undo:
            self._redo.append(self._last_state)
            self._restore_state(self._undo.pop())

    def redo_rules(self) -> None:
        if self._redo:
            self._undo.append(self._last_state)
            self._restore_state(self._redo.pop())

    def _update_undo_buttons(self) -> None:
        self.undo_btn.setEnabled(bool(self._undo) or self._snapshot_timer.isActive())
        self.redo_btn.setEnabled(bool(self._redo))

    # ======================================================================
    # Preview
    # ======================================================================
    def schedule_preview(self) -> None:
        self._update_undo_buttons()
        self._preview_timer.start()

    def _start_preview(self) -> None:
        if self._preview_job is not None:
            self._preview_job.cancel()
        self._gen += 1
        if not self.model.items:
            self._update_counts()
            return
        items = self.model.snapshot()
        engine = RenameEngine([r.clone() for r in self.rules], self.store,
                              auto_number=self.auto_number.isChecked())
        job = Job(self._gen, lambda progress, cancelled: engine.compute(items, progress, cancelled))
        job.signals.result.connect(self._on_preview)
        job.signals.progress.connect(self._on_preview_progress)
        job.signals.error.connect(lambda g, tb: g == self._gen and self._job_error("Preview failed", tb))
        self._preview_job = self.runner.start(job)

    def _on_preview_progress(self, gen: int, done: int, total: int) -> None:
        if gen != self._gen:
            return
        self.progress.setVisible(done < total)
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_text.setText(f"Reading tags… {done:,} / {total:,}")

    def _on_preview(self, gen: int, proposals) -> None:
        if gen != self._gen or proposals is None:
            return
        self._preview_job = None
        self.progress.setVisible(False)
        self.model.set_proposals(proposals)
        self._update_counts()
        self._show_details(self.table.currentIndex())
        if self._apply_when_ready:
            self._apply_when_ready = False
            self.apply()

    def _update_counts(self) -> None:
        c = self.model.counts()
        total = len(self.model.items)
        pending = c[Status.PENDING] + c[Status.WARNING]
        parts = [f"{total:,} files", f"<span style='color:{C.ACCENT_HI}'>{pending:,} to rename</span>"]
        if c[Status.WARNING]:
            parts.append(f"<span style='color:{C.WARN}'>{c[Status.WARNING]:,} warnings</span>")
        if c[Status.ERROR]:
            parts.append(f"<span style='color:{C.ERROR}'>{c[Status.ERROR]:,} errors</span>")
        if c[Status.SUCCESS]:
            parts.append(f"<span style='color:{C.OK}'>{c[Status.SUCCESS]:,} renamed</span>")
        self.counts.setText("  ·  ".join(parts))
        self.legend.setVisible(pending > 0)
        self.apply_btn.setEnabled(pending > 0)
        self.apply_btn.setText(f"Rename {pending:,} file{'s' if pending != 1 else ''}" if pending
                               else "Rename files")
        if not self.progress.isVisible():
            self.status_text.setText("Preview up to date · nothing changes on disk until you apply"
                                     if total else "Ready")

    def _apply_filter(self) -> None:
        self.proxy.set_filter(self.search.text(), self.filter_mode.currentData())

    # ======================================================================
    # Apply / history
    # ======================================================================
    def apply(self) -> None:
        if self._preview_timer.isActive() or self._preview_job is not None:
            # A preview is in flight: apply as soon as it lands, never on stale names.
            self._apply_when_ready = True
            if self._preview_timer.isActive():
                self._preview_timer.stop()
                self._start_preview()
            return
        ops = RenameEngine.plan(self.model.items, self.model.proposals)
        if not ops:
            return
        errors = self.model.counts()[Status.ERROR]
        text = f"Rename {len(ops):,} file(s)?"
        if errors:
            text += f"\n\n{errors:,} file(s) with errors will be skipped."
        text += "\n\nYou can undo this later from History."
        if QMessageBox.question(self, APP_NAME, text) != QMessageBox.Yes:
            return
        label = "; ".join(r.summary() for r in self.rules if r.enabled)[:160] or "Rename"
        dlg = QProgressDialog("Renaming files…", None, 0, len(ops), self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setWindowTitle(APP_NAME)
        job = Job(0, lambda progress, _c: self.engine.apply_plan(ops, label, progress))
        job.signals.progress.connect(lambda _g, d, t: (dlg.setMaximum(t), dlg.setValue(d)))
        job.signals.result.connect(lambda _g, res: (dlg.close(), self._on_applied(res)))
        job.signals.error.connect(lambda _g, tb: (dlg.close(), self._job_error("Rename failed", tb)))
        self.runner.start(job)

    def _on_applied(self, result) -> None:
        if not result.ok:
            msg = f"Nothing was renamed.\n\n{result.error}"
            if result.stuck:
                msg = ("Rename failed and some files could not be restored:\n\n"
                       + "\n".join(result.stuck[:20]) + f"\n\nCause: {result.error}")
            elif result.rolled_back:
                msg += "\n\nAll completed steps were rolled back. Your files are unchanged."
            QMessageBox.critical(self, APP_NAME, msg)
            self.schedule_preview()
            return
        mapping = {path_key(op.src): op.dst for op in result.ops}
        self.model.relocate(mapping, mark_success=True)
        self._update_counts()
        self.status_text.setText(f"Renamed {len(result.ops):,} file(s). Undo any time from History.")

    def _sync_more_menu(self) -> None:
        from alexed_bru.core import sendto
        self.sendto_action.setChecked(sendto.is_installed())

    def toggle_sendto(self, on: bool) -> None:
        from alexed_bru.core import sendto
        try:
            if on:
                sendto.install()
                self.status_text.setText("Added to Send To: right-click files in Explorer → Send to → "
                                         "Alexed Bulk Rename. If you move the app, tick it again.")
            else:
                sendto.remove()
                self.status_text.setText("Removed from the Send To menu.")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not change the Send To menu.\n\n{exc}")
        self.sendto_action.setChecked(sendto.is_installed())

    def show_history(self) -> None:
        HistoryDialog(self).exec()

    def rollback_batch(self, batch: Batch, redo: bool) -> bool:
        result = self.history.reapply(batch) if redo else self.history.rollback(batch)
        if not result.ok:
            QMessageBox.warning(self, APP_NAME, f"Could not {'redo' if redo else 'undo'} this batch.\n\n"
                                f"{result.error}\n\nNo files were changed.")
            return False
        ops = batch.rename_ops if redo else [o.inverse() for o in batch.rename_ops]
        self.model.relocate({path_key(o.src): o.dst for o in ops}, mark_success=False)
        self.store.invalidate()
        self.schedule_preview()
        self.status_text.setText(f"{'Re-applied' if redo else 'Rolled back'} {len(ops):,} file(s).")
        return True

    # ======================================================================
    # Presets
    # ======================================================================
    def _fill_presets_menu(self) -> None:
        menu = self.presets_menu
        menu.clear()
        menu.addAction("Save current rules as preset…", self.save_preset)
        menu.addAction("Load preset from file…", self.load_preset_dialog)
        menu.addSeparator()
        saved = sorted(presets_dir().glob("*.json"), key=lambda p: p.stem.casefold())
        menu.addSection("Your presets")
        if not saved:
            menu.addAction("(none saved yet)").setEnabled(False)
        for p in saved:
            menu.addAction(menu_text(p.stem), lambda path=p: self.load_preset(path))
        menu.addSection("Starter presets")
        for name, rules in presets.samples().items():
            menu.addAction(menu_text(name), lambda r=rules: self.set_rules([x.clone() for x in r]))
        menu.addSeparator()
        menu.addAction("Open presets folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(presets_dir()))))

    def save_preset(self) -> None:
        if not self.rules:
            QMessageBox.information(self, APP_NAME, "Add some rules first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save preset", str(presets_dir() / "My preset.json"),
                                              "Preset (*.json)")
        if path:
            presets.save(Path(path), self.rules)
            self.status_text.setText(f"Saved preset {Path(path).stem}")

    def load_preset_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load preset", str(presets_dir()), "Preset (*.json)")
        if path:
            self.load_preset(Path(path))

    def load_preset(self, path: Path) -> None:
        try:
            self.set_rules(presets.load(path))
            self.status_text.setText(f"Loaded preset {path.stem}")
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not load preset:\n{exc}")

    # ======================================================================
    # Context menu & details
    # ======================================================================
    def _table_context_menu(self, pos) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        menu = QMenu(self)
        menu.addAction("Include", lambda: self.model.set_include(rows, True))
        menu.addAction("Exclude", lambda: self.model.set_include(rows, False))
        menu.addAction("Remove from list", self.remove_selected_files)
        menu.addSeparator()
        if len(rows) == 1 and self.model.items[rows[0]].include:
            menu.addAction("Edit new name…\tF2", lambda: self.table.edit(
                self.proxy.mapFromSource(self.model.index(rows[0], COL_NEW))))
        edited = self.model.manual_rows(rows)
        if edited:
            menu.addAction(f"Reset to rule name ({len(edited)})" if len(edited) > 1 else "Reset to rule name",
                           lambda: self.model.reset_manual(edited))
        menu.addSeparator()
        menu.addAction("Copy new names", lambda: QGuiApplication.clipboard().setText(
            "\n".join(self.model.proposals[r].new_name for r in rows)))
        menu.addAction("Show in folder", lambda: self._reveal(self.model.items[rows[0]].path))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal(path: Path) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _show_details(self, index) -> None:
        self.details.clear()
        if not index.isValid():
            return
        row = self.proxy.mapToSource(index).row()
        if not 0 <= row < len(self.model.items):
            return
        for ns, values in self.model.metadata(row).items():
            if not values:
                continue
            top = QTreeWidgetItem([PROVIDERS[ns].label, "", ""])
            bold = QFont()
            bold.setWeight(QFont.DemiBold)
            top.setFont(0, bold)
            for key, value in values.items():
                child = QTreeWidgetItem([key, format_value(value, "%Y-%m-%d %H:%M:%S"), f"<{ns}:{key}>"])
                child.setForeground(0, QColor(C.DIM))
                child.setForeground(2, QColor(C.CYAN))
                top.addChild(child)
            self.details.addTopLevelItem(top)
            top.setExpanded(True)
        self.details.resizeColumnToContents(0)
        self.details.setColumnWidth(1, 360)

    def _copy_tag(self, item: QTreeWidgetItem, _col: int) -> None:
        tag = item.text(2)
        if tag:
            QGuiApplication.clipboard().setText(tag)
            self.status_text.setText(f"Copied {tag} to the clipboard")

    # ======================================================================
    # Helpers, settings & session
    # ======================================================================
    def _busy(self, text: str) -> None:
        self.status_text.setText(text)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)

    def _idle(self, text: str) -> None:
        self.progress.setVisible(False)
        self.status_text.setText(text)

    def _job_error(self, title: str, tb: str) -> None:
        self._idle(title)
        box = QMessageBox(QMessageBox.Critical, APP_NAME, title, parent=self)
        box.setDetailedText(tb)
        box.exec()

    def _load_settings(self) -> dict:
        try:
            return json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _restore_session(self) -> None:
        geo = self.settings.get("geometry")
        if geo:
            self.restoreGeometry(bytes.fromhex(geo))
        else:
            self.resize(1440, 860)
        try:
            self.set_rules(presets.load_dict(self.settings["session"]), record=False)
        except (KeyError, ValueError, TypeError):
            self.set_rules([], record=False)
        self._last_state = self._state()
        self._on_items_changed()

    def closeEvent(self, event) -> None:
        self.runner.cancel_all()
        self.settings.update(recursive=self.recursive.isChecked(),
                             auto_number=self.auto_number.isChecked(),
                             geometry=bytes(self.saveGeometry()).hex(),
                             session=presets.dump(self.rules, "session"))
        try:
            (data_dir() / "settings.json").write_text(json.dumps(self.settings, indent=1), encoding="utf-8")
        except OSError:
            pass
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        dark_title_bar(self)


# ==========================================================================
class HistoryDialog(QDialog):
    """Every applied batch, newest first, with undo and redo."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Rename history")
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        intro = QLabel("Every batch you apply is journalled here, even across restarts. "
                       "Undo puts files back; Redo applies the batch again.")
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["When", "Files", "State", "Rules"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._sync_buttons)
        lay.addWidget(self.tree, 1)
        buttons = QDialogButtonBox()
        self.undo_btn = buttons.addButton("Undo batch", QDialogButtonBox.ActionRole)
        self.redo_btn = buttons.addButton("Redo batch", QDialogButtonBox.ActionRole)
        self.undo_btn.setObjectName("Primary")
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self.undo_btn.clicked.connect(lambda: self._act(redo=False))
        self.redo_btn.clicked.connect(lambda: self._act(redo=True))
        lay.addWidget(buttons)
        self._fill()
        dark_title_bar(self)

    def _fill(self) -> None:
        self.tree.clear()
        for batch in reversed(self.window_.history.batches):
            top = QTreeWidgetItem([batch.when.strftime("%Y-%m-%d  %H:%M:%S"), f"{len(batch.ops):,}",
                                   "Undone" if batch.undone else "Applied", batch.label])
            top.setData(0, Qt.UserRole, batch.id)
            top.setForeground(2, QColor(C.FAINT if batch.undone else C.OK))
            for src, dst in batch.ops[:300]:
                top.addChild(QTreeWidgetItem(["", "", "", f"{Path(src).name}  →  {Path(dst).name}"]))
            if len(batch.ops) > 300:
                top.addChild(QTreeWidgetItem(["", "", "", f"… and {len(batch.ops) - 300:,} more"]))
            self.tree.addTopLevelItem(top)
        for col, w in enumerate((170, 70, 80)):
            self.tree.setColumnWidth(col, w)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._sync_buttons()

    def _batch(self) -> Batch | None:
        item = self.tree.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            return None
        bid = item.data(0, Qt.UserRole)
        return next((b for b in self.window_.history.batches if b.id == bid), None)

    def _sync_buttons(self, *_args) -> None:
        batch = self._batch()
        self.undo_btn.setEnabled(bool(batch and not batch.undone))
        self.redo_btn.setEnabled(bool(batch and batch.undone))

    def _act(self, redo: bool) -> None:
        batch = self._batch()
        if batch and self.window_.rollback_batch(batch, redo):
            self._fill()
