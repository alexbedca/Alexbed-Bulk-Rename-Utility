# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
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

Folders inside folders (folder renaming mode): when a batch renames a folder
and something inside it, the inside one must go first, while its path is still
valid; undoing such a batch needs the opposite order (the parent must be back
before its child can be found). `_layers` works this order out from the paths
alone, the layers run one after another, and a failure in any layer puts every
earlier layer back too. Batches without nesting take the single fast path.
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
    nested: bool = False  # folders inside renamed folders: see where_now()


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


def _ancestor_keys(p: Path):
    parent = p.parent
    while parent != p:
        yield _key(parent)
        p, parent = parent, parent.parent


def _layers(ops: list[RenameOp]) -> list[list[RenameOp]]:
    """Split a batch into layers that must run one after another (folders inside renamed folders).

    For each op, look at the folders above its source:
    * a folder that another op renames *away* (it exists now): this op runs first, inside it;
    * a folder that another op renames *into place* (it doesn't exist yet, e.g. when undoing):
      that op runs first, so this op's source exists when its turn comes.
    """
    if len(ops) < 2:
        return [ops]
    by_src = {_key(op.src): i for i, op in enumerate(ops)}
    by_dst = {_key(op.dst): i for i, op in enumerate(ops)}
    after: list[set[int]] = [set() for _ in ops]   # after[i]: ops that may run only after op i
    nested = False
    for i, op in enumerate(ops):
        for anc in _ancestor_keys(op.src):
            j = by_src.get(anc)
            if j is not None and j != i:
                after[i].add(j)        # child i, then parent j
                nested = True
                continue
            j = by_dst.get(anc)
            if j is not None and j != i:
                after[j].add(i)        # parent j comes back first, then child i
                nested = True
    if not nested:
        return [ops]
    pending = [0] * len(ops)
    for i in range(len(ops)):
        for j in after[i]:
            pending[j] += 1
    level = [n for n in range(len(ops)) if pending[n] == 0]
    layers: list[list[RenameOp]] = []
    placed = 0
    while level:
        layers.append([ops[n] for n in level])
        placed += len(level)
        nxt = []
        for n in level:
            for j in after[n]:
                pending[j] -= 1
                if pending[j] == 0:
                    nxt.append(j)
        level = nxt
    if placed != len(ops):
        raise PreflightError("Folder renames that depend on each other in a circle")
    return layers


def execute(ops: Sequence[RenameOp], progress: Callable[[int, int], None] | None = None,
            workers: int = WORKERS) -> TransactionResult:
    ops = [op for op in ops if str(op.src) != str(op.dst)]
    if not ops:
        return TransactionResult(ok=True, rolled_back=False)
    try:
        layers = _layers(ops)
    except PreflightError as exc:
        return TransactionResult(ok=False, error=str(exc), rolled_back=False)
    if len(layers) == 1:
        return _execute_flat(ops, progress, workers)

    total, done_before = len(ops), [0]

    def layer_progress(done: int, _total: int) -> None:
        if progress:
            progress(done_before[0] + done, total)

    finished: list[list[RenameOp]] = []
    for layer in layers:
        result = _execute_flat(layer, layer_progress, workers)
        if not result.ok:
            stuck = list(result.stuck)
            for earlier in reversed(finished):  # put the earlier layers back, newest first
                back = _execute_flat([op.inverse() for op in reversed(earlier)], None, workers)
                if not back.ok:
                    stuck += back.stuck or [f"{len(earlier)} item(s) not put back: {back.error}"]
            return TransactionResult(ok=False, error=result.error, stuck=stuck, nested=True,
                                     rolled_back=not stuck and (bool(finished) or result.rolled_back))
        finished.append(result.ops)
        done_before[0] += len(layer)
    return TransactionResult(ok=True, ops=[op for layer in finished for op in layer],
                             rolled_back=False, nested=True)


MAX_PATH = 260  # classic Windows limit; many programs still can't open longer paths


def too_long_after(ops: Sequence[RenameOp], limit: int = MAX_PATH, budget: int = 50000) -> list[Path]:
    """Folders whose new, longer name would push something inside them past `limit` characters.

    Only folders that get longer are checked; at most `budget` entries are looked at in total, so a
    huge tree can't stall the confirmation."""
    hits: list[Path] = []
    seen = 0
    for op in ops:
        grow = len(op.dst.name) - len(op.src.name)
        if grow <= 0 or not op.src.is_dir():
            continue
        longest = len(str(op.src))
        for root, dirs, files in os.walk(op.src):
            for name in dirs + files:
                longest = max(longest, len(root) + 1 + len(name))
            seen += len(dirs) + len(files)
            if seen > budget:
                break
        if longest + grow >= limit:
            hits.append(op.src)
        if seen > budget:
            break
    return hits


def where_now(paths: Sequence[Path], ops: Sequence[RenameOp]) -> dict[str, Path]:
    """Where each path ends up after `ops` ran in this order: {_key(original): final path}.

    A path inside a renamed folder moves with it (the folder's new name). Only ops whose source
    is a folder above some tracked path need a scan, so plain file batches stay one dict lookup."""
    current = {_key(p): (_key(p), p) for p in paths}   # key now -> (original key, path now)
    above: set[str] = set()                            # folders above a tracked path
    for p in paths:
        above.update(_ancestor_keys(p))
    for op in ops:
        src = _key(op.src)
        hit = current.pop(src, None)
        if hit is not None:
            current[_key(op.dst)] = (hit[0], op.dst)
        if src in above:
            prefix = src + os.sep
            for now in [k for k in current if k.startswith(prefix)]:
                orig, path = current.pop(now)
                moved = op.dst / Path(path).relative_to(op.src)
                current[_key(moved)] = (orig, moved)
                above.update(_ancestor_keys(moved))
    return {orig: path for orig, path in current.values()}


def _execute_flat(ops: Sequence[RenameOp], progress: Callable[[int, int], None] | None = None,
                  workers: int = WORKERS) -> TransactionResult:
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
