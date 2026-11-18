# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find duplicates: identical files in the list, and a safe way to set copies aside."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from alexed_bru import APP_NAME
from alexed_bru.core import duplicates as dup
from alexed_bru.ui.preview_model import path_key
from alexed_bru.ui.theme import C, dark_title_bar
from alexed_bru.ui.workers import Job

if TYPE_CHECKING:
    from alexed_bru.ui.main_window import MainWindow

PATH_ROLE = Qt.UserRole + 1


def human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


class DuplicatesDialog(QDialog):
    def __init__(self, window: MainWindow, paths: list[Path]) -> None:
        super().__init__(window)
        self.window_ = window
        self.groups: list[dup.DuplicateGroup] = []
        self._job: Job | None = None
        self.setWindowTitle("Find duplicates")
        self.resize(900, 560)

        lay = QVBoxLayout(self)
        intro = QLabel("Files with exactly the same content (compared byte for byte, not by name). "
                       "Ticked copies will be removed; the unticked one in each group is kept. "
                       "Nothing is deleted permanently.")
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.summary = QLabel(f"Checking {len(paths):,} file(s)…")
        self.summary.setStyleSheet("font-weight:600;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.summary)
        lay.addWidget(self.bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Remove", "Name", "Folder", "Modified"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(14)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._reveal)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.suggest_btn = QPushButton("Tick suggested copies")
        self.suggest_btn.setToolTip("Keep the original-looking, oldest file in each group; tick the rest")
        self.suggest_btn.setObjectName("Flat")
        self.suggest_btn.clicked.connect(self._fill)
        row.addWidget(self.suggest_btn)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox()
        self.move_btn = buttons.addButton(f"Move to {dup.DUPLICATES_FOLDER} folder", QDialogButtonBox.ActionRole)
        self.move_btn.setObjectName("Primary")
        self.move_btn.setToolTip(f"Move ticked copies into a {dup.DUPLICATES_FOLDER} folder beside them. "
                                 "Works on every drive and can be undone from History.")
        self.recycle_btn = buttons.addButton("Move to Recycle Bin", QDialogButtonBox.ActionRole)
        self.recycle_btn.setToolTip("Only for files on this PC's own drives. USB/SD cards and network "
                                    "drives have no Recycle Bin, so those files are left alone.")
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self.move_btn.clicked.connect(lambda: self._act(recycle=False))
        self.recycle_btn.clicked.connect(lambda: self._act(recycle=True))
        lay.addWidget(buttons)
        for w in (self.move_btn, self.recycle_btn, self.suggest_btn):
            w.setEnabled(False)

        self._start(paths)
        dark_title_bar(self)

    # ---- searching ---------------------------------------------------------
    def _start(self, paths: list[Path]) -> None:
        job = Job(0, lambda progress, cancelled: dup.find_duplicates(paths, progress, cancelled))
        job.signals.progress.connect(self._on_progress)
        job.signals.result.connect(lambda _g, groups: self._on_found(groups))
        job.signals.error.connect(lambda _g, tb: self._on_error(tb))
        self._job = self.window_.runner.start(job)

    def _on_progress(self, _gen: int, done: int, total: int) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.summary.setText(f"Comparing contents of same-size files… {done:,} / {total:,}")

    def _on_error(self, tb: str) -> None:
        self._job = None
        self.bar.setVisible(False)
        self.summary.setText("Could not check for duplicates.")
        self.summary.setToolTip(tb)

    def _on_found(self, groups) -> None:
        self._job = None
        self.bar.setVisible(False)
        self.groups = groups or []
        self._fill()

    def reject(self) -> None:
        if self._job is not None:
            self._job.cancel()
        super().reject()

    # ---- list --------------------------------------------------------------
    def _fill(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setWeight(QFont.DemiBold)
        for g in self.groups:
            top = QTreeWidgetItem(["", f"{len(g.paths)} identical files · {human_size(g.size)} each"])
            top.setFirstColumnSpanned(True)
            top.setFont(1, bold)
            top.setForeground(1, QColor(C.ACCENT_HI))
            top.setFlags(Qt.ItemIsEnabled)
            for i, p in enumerate(g.paths):
                try:
                    when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                except OSError:
                    when = ""
                child = QTreeWidgetItem(["", p.name, str(p.parent), when])
                child.setData(0, PATH_ROLE, str(p))
                child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked if i == g.keep else Qt.Checked)
                child.setToolTip(1, str(p))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        for col, w in enumerate((112, 300, 360)):
            self.tree.setColumnWidth(col, w)
        self._refresh()

    def _children(self, top: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        return [top.child(i) for i in range(top.childCount())]

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0 and item.parent() is not None:
            self._refresh()

    def _refresh(self) -> None:
        """Colour kept files, and update the summary and buttons."""
        self.tree.blockSignals(True)
        ticked = wasted = 0
        for t in range(self.tree.topLevelItemCount()):
            for child in self._children(self.tree.topLevelItem(t)):
                remove = child.checkState(0) == Qt.Checked
                child.setText(0, "" if remove else "Keep")
                child.setForeground(0, QColor(C.OK))
                child.setForeground(1, QColor(C.DIM if remove else C.TEXT))
                if remove:
                    ticked += 1
                    wasted += self.groups[t].size
        self.tree.blockSignals(False)
        if not self.groups:
            self.summary.setText("No duplicates found. Every file in the list has unique content.")
        else:
            extras = sum(len(g.paths) - 1 for g in self.groups)
            self.summary.setText(f"{len(self.groups):,} group(s) of identical files, {extras:,} extra "
                                 f"cop{'y' if extras == 1 else 'ies'}. "
                                 f"{ticked:,} ticked to remove, freeing {human_size(wasted)}.")
        self.move_btn.setEnabled(ticked > 0)
        self.recycle_btn.setEnabled(ticked > 0)
        self.suggest_btn.setEnabled(bool(self.groups))

    def ticked_paths(self) -> list[Path] | None:
        """Ticked files, or None if some group would lose every copy."""
        out: list[Path] = []
        for t in range(self.tree.topLevelItemCount()):
            children = self._children(self.tree.topLevelItem(t))
            ticked = [Path(c.data(0, PATH_ROLE)) for c in children if c.checkState(0) == Qt.Checked]
            if len(ticked) == len(children):
                return None
            out.extend(ticked)
        return out

    def _reveal(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, PATH_ROLE)
        if path:
            self.window_._reveal(Path(path))

    # ---- acting ------------------------------------------------------------
    def _act(self, recycle: bool) -> None:
        paths = self.ticked_paths()
        if paths is None:
            QMessageBox.warning(self, APP_NAME, "Each group must keep at least one file.\n\n"
                                "Untick one copy in every group before continuing.")
            return
        if not paths:
            return
        if recycle:
            refused = [p for p in paths if not dup.can_recycle(p)]
            if len(refused) == len(paths):
                QMessageBox.information(self, APP_NAME, "These files are on a USB/SD card or network drive, "
                                        "which has no Recycle Bin.\n\nUse "
                                        f"“Move to {dup.DUPLICATES_FOLDER} folder” instead.")
                return
            text = (f"Move {len(paths) - len(refused):,} file(s) to the Recycle Bin?\n\n"
                    "You can restore them from the Recycle Bin, but not from History.")
            if refused:
                text += (f"\n\n{len(refused):,} file(s) on a drive without a Recycle Bin "
                         "will be left alone.")
        else:
            text = (f"Move {len(paths):,} file(s) into a “{dup.DUPLICATES_FOLDER}” folder next to "
                    "each one?\n\nYou can undo this later from History.")
        if QMessageBox.question(self, APP_NAME, text) != QMessageBox.Yes:
            return

        if recycle:
            failed = set(dup.recycle(paths))
            removed = [p for p in paths if p not in failed]
            message = f"Moved {len(removed):,} file(s) to the Recycle Bin."
            if failed:
                message += f" {len(failed):,} file(s) were left in place."
        else:
            result = dup.move_to_folder(paths, self.window_.history)
            if not result.ok:
                QMessageBox.critical(self, APP_NAME, f"Nothing was moved.\n\n{result.error}")
                return
            removed = [op.src for op in result.ops]
            message = (f"Moved {len(removed):,} file(s) to {dup.DUPLICATES_FOLDER} folders. "
                       "Undo any time from History.")
        self.window_.forget_files(removed)
        self.window_.status_text.setText(message)
        gone = {path_key(p) for p in removed}
        for g in self.groups:
            g.paths = [p for p in g.paths if path_key(p) not in gone]
            g.keep = dup.suggest_keep(g.paths) if g.paths else 0
        self.groups = [g for g in self.groups if len(g.paths) > 1]
        self._fill()
        QMessageBox.information(self, APP_NAME, message)
