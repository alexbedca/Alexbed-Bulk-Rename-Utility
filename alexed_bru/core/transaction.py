"""Transactional renaming: all-or-nothing, with a two-phase commit.

Phase 1 moves every source to a unique temporary name in its own folder.
Phase 2 moves each temporary name to its final name. This makes swaps
(A→B, B→A), cycles and case-only renames on case-insensitive filesystems
safe. If any step fails, every completed step is reversed in reverse order.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from alexed_bru.core.validation import fold


@dataclass(frozen=True, slots=True)
class RenameOp:
    src: Path
    dst: Path

    def inverse(self) -> "RenameOp":
        return RenameOp(self.dst, self.src)


@dataclass
class TransactionResult:
    ok: bool
    ops: list[RenameOp] = field(default_factory=list)
    error: str = ""
    rolled_back: bool = True
    stuck: list[str] = field(default_factory=list)  # paths rollback could not restore


class PreflightError(Exception):
    pass


def _key(p: Path) -> str:
    return fold(os.path.normpath(str(p)))


def preflight(ops: Sequence[RenameOp]) -> None:
    sources = {_key(op.src) for op in ops}
    seen_dst: set[str] = set()
    for op in ops:
        if not op.src.exists():
            raise PreflightError(f"Missing source: {op.src}")
        k = _key(op.dst)
        if k in seen_dst:
            raise PreflightError(f"Two files would be renamed to {op.dst.name}")
        seen_dst.add(k)
        if op.dst.exists() and k not in sources:
            raise PreflightError(f"Target already exists: {op.dst}")


def _move(src: Path, dst: Path) -> None:
    # os.rename silently overwrites on POSIX; refuse explicitly everywhere.
    if os.path.lexists(dst) and _key(src) != _key(dst):
        raise FileExistsError(f"Refusing to overwrite {dst}")
    os.rename(src, dst)


def execute(ops: Sequence[RenameOp], progress: Callable[[int, int], None] | None = None,
            ) -> TransactionResult:
    ops = [op for op in ops if str(op.src) != str(op.dst)]
    if not ops:
        return TransactionResult(ok=True, rolled_back=False)
    try:
        preflight(ops)
    except PreflightError as exc:
        return TransactionResult(ok=False, error=str(exc), rolled_back=False)

    total = len(ops) * 2
    done_steps: list[tuple[Path, Path]] = []  # (from, to) actually performed
    temps: list[Path] = []
    tag = uuid.uuid4().hex[:8]
    try:
        for i, op in enumerate(ops):
            tmp = op.src.with_name(f".~abru-{tag}-{i}.tmp")
            _move(op.src, tmp)
            done_steps.append((op.src, tmp))
            temps.append(tmp)
            if progress and i % 25 == 0:
                progress(i + 1, total)
        for i, (op, tmp) in enumerate(zip(ops, temps)):
            _move(tmp, op.dst)
            done_steps.append((tmp, op.dst))
            if progress and i % 25 == 0:
                progress(len(ops) + i + 1, total)
    except OSError as exc:
        stuck = _rollback(done_steps)
        return TransactionResult(ok=False, error=f"{exc.__class__.__name__}: {exc}",
                                 rolled_back=not stuck, stuck=stuck)
    if progress:
        progress(total, total)
    return TransactionResult(ok=True, ops=list(ops), rolled_back=False)


def _rollback(steps: list[tuple[Path, Path]]) -> list[str]:
    stuck: list[str] = []
    for frm, to in reversed(steps):
        try:
            os.rename(to, frm)
        except OSError:
            stuck.append(f"{to} (should be {frm})")
    return stuck
