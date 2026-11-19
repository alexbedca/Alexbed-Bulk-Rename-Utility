# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flatten folder: preview moving every file from the subfolders up into one folder, then do it."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from alexed_bru import APP_NAME
from alexed_bru.core import flatten as fl
from alexed_bru.ui.theme import C, dark_title_bar
from alexed_bru.ui.workers import Job

if TYPE_CHECKING:
    from alexed_bru.ui.main_window import MainWindow

SHOW_MAX = 2000  # rows drawn in the preview; the summary always counts everything


class FlattenDialog(QDialog):
    def __init__(self, window: MainWindow, folder: Path | None = None) -> None:
        super().__init__(window)
        self.window_ = window
        self.plan: fl.FlattenPlan | None = None
        self._job: Job | None = None
        self._gen = 0
        self.setWindowTitle("Flatten folder")
        self.resize(940, 600)
        lay = QVBoxLayout(self)

        intro = QLabel("Moves every file from the subfolders up into one folder, then removes the subfolders "
                       "that end up empty. Check the preview first; you can undo it later from History.")
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("Folder"))
        self.folder = QLineEdit(str(folder) if folder else "")
        self.folder.setReadOnly(True)
        self.folder.setPlaceholderText("Choose the top folder…")
        row.addWidget(self.folder, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self.choose_folder)
        row.addWidget(choose)
        lay.addLayout(row)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Levels"))
        self.depth = QComboBox()
        self.depth.addItem("All subfolders", None)
        self.depth.addItem("First level only", 1)
        opts.addWidget(self.depth)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Same name"))
        self.clash = QComboBox()
        self.clash.addItem("Add a number: cover (1).jpg", fl.CLASH_NUMBER)
        self.clash.addItem("Add the folder name: Album A - cover.jpg", fl.CLASH_FOLDER)
        opts.addWidget(self.clash)
        opts.addStretch(1)
        lay.addLayout(opts)
        opts2 = QHBoxLayout()
        self.skip_dups = QCheckBox("Leave _Duplicates folders alone")
        self.skip_dups.setChecked(True)
        self.skip_clutter = QCheckBox("Leave Windows files (Thumbs.db, desktop.ini) in place")
        self.skip_clutter.setChecked(True)
        opts2.addWidget(self.skip_dups)
        opts2.addWidget(self.skip_clutter)
        opts2.addStretch(1)
        lay.addLayout(opts2)
        for w in (self.depth, self.clash):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.skip_dups, self.skip_clutter):
            w.toggled.connect(self.refresh)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight:600;")
        lay.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        lay.addWidget(self.bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["From (inside the folder)", "New name in the top folder", "Note"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 300)
        lay.addWidget(self.tree, 1)

        self.add_to_list = QCheckBox("Then add the files to the rename list")
        self.add_to_list.setChecked(True)
        self.add_to_list.setToolTip("Load the flattened folder into the preview, ready for rename rules")
        lay.addWidget(self.add_to_list)

        buttons = QDialogButtonBox()
        self.go = buttons.addButton("Flatten", QDialogButtonBox.AcceptRole)
        self.go.setObjectName("Primary")
        self.go.setEnabled(False)
        self.go.clicked.connect(self.flatten)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        dark_title_bar(self)
        self.refresh()

    # ---- planning -------------------------------------------------------------
    def choose_folder(self) -> None:
        start = self.folder.text() or self.window_.settings.get("last_dir", "")
        chosen = QFileDialog.getExistingDirectory(self, "Folder to flatten", start)
        if chosen:
            self.folder.setText(str(Path(chosen)))
            self.refresh()

    def refresh(self, *_args) -> None:
        self.plan = None
        self.go.setEnabled(False)
        root = Path(self.folder.text()) if self.folder.text() else None
        if root is None or not root.is_dir():
            self.summary.setText("Choose the folder whose subfolders you want to empty into it.")
            self.tree.clear()
            return
        if self._job is not None:
            self._job.cancel()
        self._gen += 1
        options = dict(depth=self.depth.currentData(), clash=self.clash.currentData(),
                       skip_duplicates_folders=self.skip_dups.isChecked(),
                       skip_clutter=self.skip_clutter.isChecked())
        self.summary.setText("Looking through the subfolders…")
        self.bar.show()
        job = Job(self._gen, lambda _p, cancelled: fl.plan_flatten(root, cancelled=cancelled, **options))
        job.signals.result.connect(self._on_plan)
        job.signals.error.connect(lambda _g, tb: self._show_error(tb))
        self._job = self.window_.runner.start(job)

    def _on_plan(self, gen: int, plan) -> None:
        if gen != self._gen or plan is None:
            return
        self._job = None
        self.bar.hide()
        self.plan = plan
        self.tree.clear()
        for m in plan.moves[:SHOW_MAX]:
            item = QTreeWidgetItem([m.relative, m.dst.name, "Renamed: name was taken" if m.renamed else ""])
            if m.renamed:
                item.setForeground(1, QColor(C.WARN))
                item.setForeground(2, QColor(C.WARN))
            self.tree.addTopLevelItem(item)
        for path, reason in plan.skipped[:SHOW_MAX]:
            rel = str(path.relative_to(plan.root)) if path != plan.root else str(path)
            item = QTreeWidgetItem([rel, "(stays where it is)", reason])
            for col in range(3):
                item.setForeground(col, QColor(C.FAINT))
            self.tree.addTopLevelItem(item)
        if not plan.moves:
            empty = fl.empty_folders(plan)
            if empty:
                self.summary.setText(f"No files to move, but {len(empty):,} subfolder(s) are empty.")
                self.go.setText(f"Remove {len(empty):,} empty subfolder(s)")
                self.go.setEnabled(True)
            else:
                self.summary.setText("Nothing to flatten: there are no files in subfolders"
                                     + (" (some were skipped, see the list)." if plan.skipped else "."))
            return
        folders = len(plan.folders)
        text = (f"Moves {len(plan.moves):,} file(s) from {folders:,} subfolder(s) up into "
                f"“{plan.root.name}”.")
        if plan.renamed:
            text += f" {plan.renamed:,} get a new name because the name was taken."
        if plan.skipped:
            text += f" {len(plan.skipped):,} item(s) stay where they are."
        if len(plan.moves) + len(plan.skipped) > SHOW_MAX:
            text += f" (Showing the first {SHOW_MAX:,} rows.)"
        self.summary.setText(text)
        self.go.setText(f"Flatten {len(plan.moves):,} file(s)")
        self.go.setEnabled(True)

    def _show_error(self, tb: str) -> None:
        self._job = None
        self.bar.hide()
        self.summary.setText("Could not read the folder.")
        self.summary.setToolTip(tb)

    # ---- doing it -------------------------------------------------------------
    def flatten(self) -> None:
        plan = self.plan
        if plan is None:
            return
        if not plan.moves:
            fl.apply_flatten(plan, self.window_.history)
            removed = sum(1 for f in plan.folders if not f.exists())
            QMessageBox.information(self, APP_NAME, f"Removed {removed:,} empty subfolder(s). "
                                    "Undo any time from History.")
            self.refresh()
            return
        text = (f"Move {len(plan.moves):,} file(s) up into “{plan.root}” and remove the subfolders "
                "that end up empty?\n\nYou can undo this later from History.")
        if QMessageBox.question(self, APP_NAME, text) != QMessageBox.Yes:
            return
        self.go.setEnabled(False)
        self.bar.show()
        history = self.window_.history
        job = Job(0, lambda progress, _c: fl.apply_flatten(plan, history, progress))
        job.signals.result.connect(lambda _g, result: self._done(plan, result))
        job.signals.error.connect(lambda _g, tb: (self.bar.hide(), self.window_._job_error("Flatten failed", tb)))
        self.window_.runner.start(job)

    def _done(self, plan: fl.FlattenPlan, result) -> None:
        self.bar.hide()
        if not result.ok:
            msg = f"Nothing was moved.\n\n{result.error}"
            if result.stuck:
                msg = ("Flattening failed and some files could not be put back:\n\n" + "\n".join(result.stuck[:20]))
            elif result.rolled_back:
                msg += "\n\nEvery file is back where it was."
            QMessageBox.critical(self, APP_NAME, msg)
            self.refresh()
            return
        left = fl.left_folders(plan)
        message = f"Moved {len(result.ops):,} file(s) into “{plan.root.name}”. Undo any time from History."
        if left:
            message += (f"\n\n{len(left):,} subfolder(s) were kept because they still hold skipped files: "
                        + ", ".join(str(f.relative_to(plan.root)) for f in left[:5])
                        + (" …" if len(left) > 5 else ""))
        self.window_.forget_files([op.src for op in result.ops])
        if self.add_to_list.isChecked():
            self.window_.add_paths([plan.root])
        self.window_.status_text.setText(message.split("\n")[0])
        QMessageBox.information(self, APP_NAME, message)
        self.accept()
