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


@dataclass
class Batch:
    id: str
    timestamp: str
    label: str
    ops: list[tuple[str, str]]
    undone: bool = False

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

    def record(self, ops: list[RenameOp], label: str) -> Batch:
        # A new batch invalidates the redo branch, as in any editor.
        self.batches = [b for b in self.batches if not b.undone]
        batch = Batch(uuid.uuid4().hex, datetime.now().isoformat(timespec="seconds"), label,
                      [(str(o.src), str(o.dst)) for o in ops])
        self.batches.append(batch)
        self.save()
        return batch

    # ---- undo / redo ------------------------------------------------------
    def last_applied(self) -> Batch | None:
        return next((b for b in reversed(self.batches) if not b.undone), None)

    def next_redo(self) -> Batch | None:
        undone = [b for b in self.batches if b.undone]
        return undone[0] if undone else None

    def rollback(self, batch: Batch) -> TransactionResult:
        result = execute([op.inverse() for op in batch.rename_ops])
        if result.ok:
            batch.undone = True
            self.save()
        return result

    def reapply(self, batch: Batch) -> TransactionResult:
        result = execute(batch.rename_ops)
        if result.ok:
            batch.undone = False
            self.save()
        return result
