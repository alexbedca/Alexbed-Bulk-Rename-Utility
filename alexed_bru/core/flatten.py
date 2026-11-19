# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flatten a folder: move every file from its subfolders up into it, then remove the emptied subfolders.

    plan = plan_flatten(Path(r"D:\\Music\\Adele"))      # pure: reads names only
    result = apply_flatten(plan, history)              # one transaction, undoable from History

Safety (same model as renaming, see docs/ARCHITECTURE.md):
* Planning never touches the disk; the preview shows every move first.
* All moves run as one transaction: if any file is locked, every move is undone.
* Only subfolders that end up **empty** are removed; anything still holding a skipped or
  locked file stays. The batch is journalled with its folder list and the folders it removed
  (also ones that never held a file), so History's undo puts every file back and recreates
  the folder tree exactly; redo flattens again. Removing only empty subfolders is undoable too.
* Folder links (junctions, symbolic links) are never followed; `_Duplicates` folders and
  Windows' own clutter files (Thumbs.db, desktop.ini) are left alone by default.
* Moves stay inside the chosen folder, so they are renames on the same drive.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from alexed_bru.core.history import SET_ASIDE_FOLDER, History, remove_empty
from alexed_bru.core.models import join_name, split_name
from alexed_bru.core.transaction import RenameOp, TransactionResult, execute
from alexed_bru.core.validation import fold, name_errors, numbered

CLUTTER = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db"}
TEMP_PREFIX = ".~abru-"
CLASH_NUMBER, CLASH_FOLDER = "number", "folder"


@dataclass
class FlattenMove:
    src: Path
    dst: Path
    renamed: bool          # the name changed to avoid a clash

    @property
    def relative(self) -> str:
        return str(self.src.relative_to(self.dst.parent))


@dataclass
class FlattenPlan:
    root: Path
    moves: list[FlattenMove] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)          # subfolders that will be emptied
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def renamed(self) -> int:
        return sum(1 for m in self.moves if m.renamed)

    @property
    def ops(self) -> list[RenameOp]:
        return [RenameOp(m.src, m.dst) for m in self.moves]


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def plan_flatten(root: Path, depth: int | None = None, clash: str = CLASH_NUMBER,
                 skip_duplicates_folders: bool = True, skip_clutter: bool = True,
                 cancelled: Callable[[], bool] = lambda: False) -> FlattenPlan | None:
    """Plan moving files from subfolders of `root` (all levels, or `depth` levels) into `root`.

    `clash`: "number" gives a taken name " (1)", " (2)"...; "folder" puts the subfolder path in
    front ("Album A - CD1 - 01.mp3"), numbering only if that is taken too. None if cancelled.
    """
    root = Path(root)
    plan = FlattenPlan(root)
    try:
        taken = {fold(n) for n in os.listdir(root)}  # names already in the top folder stay
    except OSError as exc:
        plan.skipped.append((root, f"Can't read the folder: {exc}"))
        return plan

    for current, dirs, files in os.walk(root, followlinks=False):
        if cancelled():
            return None
        here = Path(current)
        level = len(here.relative_to(root).parts)
        keep = []
        for d in sorted(dirs, key=str.casefold):
            sub = here / d
            if _is_link(sub):
                plan.skipped.append((sub, "Folder link: not followed"))
            elif skip_duplicates_folders and d == SET_ASIDE_FOLDER:
                plan.skipped.append((sub, f"{SET_ASIDE_FOLDER} folder left alone"))
            elif depth is not None and level >= depth:
                plan.skipped.append((sub, f"Deeper than {depth} level(s)"))
            else:
                keep.append(d)
        dirs[:] = keep
        if level == 0:
            continue  # files already in the top folder don't move
        plan.folders.append(here)
        for f in sorted(files, key=str.casefold):
            src = here / f
            if f.startswith(TEMP_PREFIX):
                plan.skipped.append((src, "Temporary file of an interrupted rename"))
                continue
            if skip_clutter and f.lower() in CLUTTER:
                plan.skipped.append((src, "Windows system file left in place"))
                continue
            if _is_link(src):
                plan.skipped.append((src, "Link: not moved"))
                continue
            name = f
            if fold(name) in taken and clash == CLASH_FOLDER:
                stem, ext = split_name(f)
                prefix = " - ".join(here.relative_to(root).parts)
                name = join_name(f"{prefix} - {stem}", ext)
            if name_errors(name):  # e.g. a folder prefix made it too long
                name = f
            if fold(name) in taken:
                n = 1
                while fold(numbered(name, n)) in taken:
                    n += 1
                name = numbered(name, n)
            taken.add(fold(name))
            plan.moves.append(FlattenMove(src, root / name, renamed=name != f))
    return plan


def apply_flatten(plan: FlattenPlan, history: History | None = None,
                  progress: Callable[[int, int], None] | None = None) -> TransactionResult:
    """Run the moves as one transaction, then remove subfolders left empty; journalled for undo."""
    existed = [f for f in plan.folders if f.is_dir()]
    if plan.moves:
        result = execute(plan.ops, progress)
        if not result.ok:
            return result
        label = f"Flattened {plan.root.name}: {len(result.ops)} file(s) moved up"
    else:  # nothing to move: just tidy away empty subfolders
        result = TransactionResult(ok=True, rolled_back=False)
        label = f"Removed empty subfolders in {plan.root.name}"
    remove_empty(plan.folders)
    removed = [f for f in existed if not f.exists()]
    if history is not None and (result.ops or removed):
        history.record(result.ops, label, folders=plan.folders, removed_folders=removed)
    return result


def empty_folders(plan: FlattenPlan) -> list[Path]:
    """Planned subfolders with no files anywhere inside (they would simply be removed)."""
    return [f for f in plan.folders if not any(p.is_file() or p.is_symlink() for p in f.rglob("*"))]


def left_folders(plan: FlattenPlan) -> list[Path]:
    """Subfolders still there after flattening (they held skipped files)."""
    return [f for f in plan.folders if f.exists()]
