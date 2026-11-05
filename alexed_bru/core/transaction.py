"""Transactional renaming: all-or-nothing.

Only operations whose target is currently occupied by another file in the
same batch need a temporary hop: swaps (A→B, B→A), chains (A→B, B→C),
cycles, and case-only renames on case-insensitive filesystems. Everything
else is renamed straight to its final name. The work runs in three phases:

    1. staged sources  → unique temporary names
    2. direct renames  → final names
    3. temporary names → final names

Within a phase every step touches distinct paths, so steps run in parallel
(file renames are I/O-bound, often slowed by antivirus scanning). If any
step fails, every completed step is reversed, newest phase first, and the
disk ends up exactly as it was.
"""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from alexed_bru.core.validation import fold

WORKERS = 8
_WINDOWS = os.name == "nt"


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


class _Listings:
    """One directory listing per folder instead of one stat per file."""

    def __init__(self) -> None:
        self._cache: dict[str, set[str]] = {}

    def exists(self, p: Path) -> bool:
        folder = str(p.parent)
        if folder not in self._cache:
            try:
                self._cache[folder] = {fold(n) for n in os.listdir(folder)}
            except OSError:
                self._cache[folder] = set()
        return fold(p.name) in self._cache[folder]


def preflight(ops: Sequence[RenameOp]) -> None:
    listings = _Listings()
    sources = {_key(op.src) for op in ops}
    seen_dst: set[str] = set()
    for op in ops:
        if not listings.exists(op.src):
            raise PreflightError(f"Missing source: {op.src}")
        k = _key(op.dst)
        if k in seen_dst:
            raise PreflightError(f"Two files would be renamed to {op.dst.name}")
        seen_dst.add(k)
        if k not in sources and listings.exists(op.dst):
            raise PreflightError(f"Target already exists: {op.dst}")


def _move(src: Path, dst: Path) -> None:
    # Windows' rename already refuses to overwrite. POSIX silently replaces,
    # so check there (a tiny race window remains; preflight covers the batch).
    if not _WINDOWS and os.path.lexists(dst) and _key(src) != _key(dst):
        raise FileExistsError(f"Refusing to overwrite {dst}")
    os.rename(src, dst)


class _Phase:
    """Runs independent rename steps in parallel and records what completed."""

    def __init__(self, done: list[tuple[Path, Path]], counter: list[int], total: int,
                 progress: Callable[[int, int], None] | None) -> None:
        self.done = done
        self.counter = counter
        self.total = total
        self.progress = progress
        self.lock = threading.Lock()
        self.failure: BaseException | None = None

    def _step(self, frm: Path, to: Path) -> None:
        if self.failure is not None:
            return  # another step failed: stop starting new work
        try:
            _move(frm, to)
        except OSError as exc:
            with self.lock:
                if self.failure is None:
                    self.failure = exc
            return
        with self.lock:
            self.done.append((frm, to))
            self.counter[0] += 1
            n = self.counter[0]
        if self.progress and (n % 50 == 0 or n == self.total):
            self.progress(n, self.total)

    def run(self, steps: list[tuple[Path, Path]], workers: int) -> None:
        if not steps:
            return
        if workers <= 1 or len(steps) < 64:
            for frm, to in steps:
                self._step(frm, to)
                if self.failure is not None:
                    break
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda s: self._step(*s), steps))
        if self.failure is not None:
            raise self.failure


def execute(ops: Sequence[RenameOp], progress: Callable[[int, int], None] | None = None,
            workers: int = WORKERS) -> TransactionResult:
    ops = [op for op in ops if str(op.src) != str(op.dst)]
    if not ops:
        return TransactionResult(ok=True, rolled_back=False)
    try:
        preflight(ops)
    except PreflightError as exc:
        return TransactionResult(ok=False, error=str(exc), rolled_back=False)

    sources = {_key(op.src) for op in ops}
    tag = uuid.uuid4().hex[:8]
    staged: list[tuple[RenameOp, Path]] = []
    direct: list[RenameOp] = []
    for i, op in enumerate(ops):
        if _key(op.dst) in sources:  # target is occupied by a file in this batch
            staged.append((op, op.src.with_name(f".~abru-{tag}-{i}.tmp")))
        else:
            direct.append(op)

    phases = [
        [(op.src, tmp) for op, tmp in staged],
        [(op.src, op.dst) for op in direct],
        [(tmp, op.dst) for op, tmp in staged],
    ]
    total = sum(len(p) for p in phases)
    completed: list[list[tuple[Path, Path]]] = []
    counter = [0]
    try:
        for steps in phases:
            done: list[tuple[Path, Path]] = []
            completed.append(done)
            _Phase(done, counter, total, progress).run(steps, workers)
    except OSError as exc:
        stuck = _rollback(completed)
        return TransactionResult(ok=False, error=f"{exc.__class__.__name__}: {exc}",
                                 rolled_back=not stuck, stuck=stuck)
    if progress:
        progress(total, total)
    return TransactionResult(ok=True, ops=list(ops), rolled_back=False)


def _rollback(completed: list[list[tuple[Path, Path]]]) -> list[str]:
    """Undo completed steps, newest phase first (steps within a phase are independent)."""
    stuck: list[str] = []
    for done in reversed(completed):
        for frm, to in reversed(done):
            try:
                os.rename(to, frm)
            except OSError:
                stuck.append(f"{to} (should be {frm})")
    return stuck
