# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent journal of applied batches: undo/redo that survives restarts."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from alexed_bru.core.transaction import RenameOp, TransactionResult, execute

MAX_BATCHES = 500
# Folder that "Find duplicates" moves extra copies into (core/duplicates.py). Undo removes it again
# when that leaves it empty; redo recreates it. Defined here so duplicates.py can import it.
SET_ASIDE_FOLDER = "_Duplicates"


@dataclass
class Batch:
    id: str
    timestamp: str
    label: str
    ops: list[tuple[str, str]]
    undone: bool = False
    # Folders this batch creates or removes (Find duplicates, Flatten folder). Undo and redo
    # recreate the ones the moves need and remove the ones left empty. Older journals lack it.
    folders: list[str] = field(default_factory=list)

    @property
    def rename_ops(self) -> list[RenameOp]:
        return [RenameOp(Path(s), Path(d)) for s, d in self.ops]

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


@dataclass
class History:
    path: Path
    batches: list[Batch] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "History":
        history = cls(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            history.batches = [Batch(**{**b, "ops": [tuple(o) for o in b["ops"]]})
                               for b in raw.get("batches", [])]
        except (OSError, ValueError, KeyError, TypeError):
            history.batches = []
        return history

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"version": 1, "batches": [asdict(b) for b in self.batches[-MAX_BATCHES:]]}
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crash never leaves half a journal

    def record(self, ops: list[RenameOp], label: str, folders=()) -> Batch:
        # A new batch invalidates the redo branch, as in any editor.
        self.batches = [b for b in self.batches if not b.undone]
        batch = Batch(uuid.uuid4().hex, datetime.now().isoformat(timespec="seconds"), label,
                      [(str(o.src), str(o.dst)) for o in ops], folders=[str(f) for f in folders])
        self.batches.append(batch)
        self.save()
        return batch

    def clear(self) -> None:
        """Forget every batch (the user's choice). Files on disk are not touched."""
        self.batches = []
        self.save()

    # ---- undo / redo ------------------------------------------------------
    def last_applied(self) -> Batch | None:
        return next((b for b in reversed(self.batches) if not b.undone), None)

    def next_redo(self) -> Batch | None:
        undone = [b for b in self.batches if b.undone]
        return undone[0] if undone else None

    def rollback(self, batch: Batch) -> TransactionResult:
        return self._run(batch, [op.inverse() for op in batch.rename_ops], undone=True)

    def reapply(self, batch: Batch) -> TransactionResult:
        return self._run(batch, batch.rename_ops, undone=False)

    def _run(self, batch: Batch, ops: list[RenameOp], undone: bool) -> TransactionResult:
        managed = managed_folders(batch)
        created = ensure_folders(managed, {op.dst.parent for op in ops})
        result = execute(ops)
        if result.ok:
            batch.undone = undone
            self.save()
            remove_empty(managed)
        else:
            remove_empty(created)
        return result


def managed_folders(batch: Batch) -> list[Path]:
    """Folders a batch may create and remove: its recorded list, or (journals from before 1.2)
    the _Duplicates folders it moved files into. Never anything else."""
    if batch.folders:
        return [Path(f) for f in batch.folders]
    return sorted({op.dst.parent for op in batch.rename_ops if op.dst.parent.name == SET_ASIDE_FOLDER})


def ensure_folders(managed, needed) -> list[Path]:
    """Create the managed folders that moves into `needed` require; returns what was created."""
    created = []
    for folder in sorted(set(managed) & set(needed), key=lambda f: len(f.parts)):  # parents first
        if folder.exists():
            continue
        missing = [p for p in [folder, *folder.parents] if not p.exists()]
        try:
            folder.mkdir(parents=True)
        except OSError:
            continue  # the transaction will then fail cleanly on the missing folder
        created.extend(reversed(missing))
    return created


def remove_empty(folders) -> None:
    """Remove folders that are empty, deepest first (a parent may empty once its child goes)."""
    for folder in sorted(set(map(Path, folders)), key=lambda f: len(f.parts), reverse=True):
        try:
            folder.rmdir()  # only succeeds when the folder is empty
        except OSError:
            pass
