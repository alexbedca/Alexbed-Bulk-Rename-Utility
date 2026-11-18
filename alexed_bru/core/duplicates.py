# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find files with identical content and set the extra copies aside safely.

Finding is read-only and cheap on large libraries:

    1. group by file size (no reading at all; most files drop out here)
    2. hash the first 64 KB of same-size files
    3. hash the whole file only when the first 64 KB also match

Two ways to remove the extra copies, neither of them permanent:

* ``move_to_folder``: moves each copy into a ``_Duplicates`` folder next to it,
  through the same all-or-nothing transaction as renaming, and journals it in
  History so it can be undone like any rename batch.
* ``recycle``: sends copies to the Windows Recycle Bin, only on drives that
  have one (never on USB/SD cards or network drives, where Windows would
  delete permanently instead).
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Sequence

from alexed_bru.core.history import History
from alexed_bru.core.transaction import RenameOp, TransactionResult, execute

HEAD_BYTES = 64 * 1024
CHUNK = 1024 * 1024
DUPLICATES_FOLDER = "_Duplicates"

# Names that look like a copy: "x (1)", "x - Copy", "x copy 2", "Copy of x", "x_copy".
# Only small numbers at the very end, so "Live (1999)" is not mistaken for a copy.
_COPY_MARK = re.compile(r"(\s\(\d{1,2}\)$|[\s_-]+copy(\s*\(?\d{1,2}\)?)?$|^copy of\s)", re.IGNORECASE)


@dataclass
class DuplicateGroup:
    size: int
    paths: list[Path]   # identical content; paths[keep] is the suggested original
    keep: int = 0

    @property
    def extras(self) -> list[Path]:
        return [p for i, p in enumerate(self.paths) if i != self.keep]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.paths) - 1)


def _hash(path: Path, limit: int | None, cancelled: Callable[[], bool]) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if limit is not None:
                h.update(f.read(limit))
            else:
                while chunk := f.read(CHUNK):
                    if cancelled():
                        return None
                    h.update(chunk)
    except OSError:
        return None  # unreadable (locked, gone): never call it a duplicate
    return h.hexdigest()


def looks_like_copy(name: str) -> bool:
    return bool(_COPY_MARK.search(Path(name).stem))


def suggest_keep(paths: Sequence[Path]) -> int:
    """Index of the copy to keep: not named like a copy, then oldest, then shortest name."""
    def score(i: int):
        p = paths[i]
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = float("inf")
        return (looks_like_copy(p.name), mtime, len(p.name), str(p).casefold())
    return min(range(len(paths)), key=score)


def find_duplicates(paths: Iterable[Path],
                    progress: Callable[[int, int], None] | None = None,
                    cancelled: Callable[[], bool] = lambda: False) -> list[DuplicateGroup] | None:
    """Groups of identical files (empty files are ignored). None if cancelled."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    seen: set[str] = set()
    for p in paths:
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
            continue
        seen.add(key)
        try:
            size = os.stat(p).st_size
        except OSError:
            continue
        if size > 0:
            by_size[size].append(Path(p))

    candidates = [(size, group) for size, group in by_size.items() if len(group) > 1]
    total = sum(len(g) for _, g in candidates)
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress and (done % 20 == 0 or done == total):
            progress(done, total)

    groups: list[DuplicateGroup] = []
    for size, group in candidates:
        by_head: dict[str, list[Path]] = defaultdict(list)
        for p in group:
            if cancelled():
                return None
            digest = _hash(p, HEAD_BYTES, cancelled)
            if digest is not None:
                by_head[digest].append(p)
        for same_head in by_head.values():
            if len(same_head) < 2:
                for _ in same_head:
                    tick()
                continue
            if size <= HEAD_BYTES:
                full = {"head": same_head}  # the head already covered the whole file
            else:
                full = defaultdict(list)
                for p in same_head:
                    digest = _hash(p, None, cancelled)
                    if cancelled():
                        return None
                    if digest is not None:
                        full[digest].append(p)
            for same in full.values():
                if len(same) > 1:
                    same.sort(key=lambda q: str(q).casefold())
                    groups.append(DuplicateGroup(size, same, suggest_keep(same)))
            for _ in same_head:
                tick()
        # files whose head could not be read still count towards progress
        for _ in range(len(group) - sum(len(v) for v in by_head.values())):
            tick()
    groups.sort(key=lambda g: (-g.wasted, str(g.paths[0]).casefold()))
    return groups


# ---- setting copies aside ---------------------------------------------------
def _free_name(folder: Path, name: str, taken: set[str]) -> Path:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    n = 1
    candidate = name
    while candidate.casefold() in taken or (folder / candidate).exists():
        n += 1
        candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
    taken.add(candidate.casefold())
    return folder / candidate


def move_plan(extras: Iterable[Path]) -> list[RenameOp]:
    """Where each copy goes: <its folder>\\_Duplicates\\<same name>, never overwriting."""
    taken: dict[Path, set[str]] = defaultdict(set)
    ops = []
    for p in extras:
        target_dir = p.parent / DUPLICATES_FOLDER
        ops.append(RenameOp(p, _free_name(target_dir, p.name, taken[target_dir])))
    return ops


def move_to_folder(extras: Sequence[Path], history: History | None = None,
                   progress: Callable[[int, int], None] | None = None) -> TransactionResult:
    """Move copies into _Duplicates folders as one transaction, journalled for undo."""
    ops = move_plan(extras)
    if not ops:
        return TransactionResult(ok=True, rolled_back=False)
    created = []
    for folder in sorted({op.dst.parent for op in ops}):
        if not folder.exists():
            try:
                folder.mkdir()
            except OSError as exc:
                _remove_empty(created)
                return TransactionResult(ok=False, error=f"Could not create {folder}: {exc}",
                                         rolled_back=False)
            created.append(folder)
    result = execute(ops, progress)
    if not result.ok:
        _remove_empty(created)
    elif history is not None:
        history.record(result.ops, f"Moved {len(result.ops)} duplicate(s) to {DUPLICATES_FOLDER}")
    return result


def _remove_empty(folders: Iterable[Path]) -> None:
    for folder in folders:
        try:
            folder.rmdir()
        except OSError:
            pass


# ---- Recycle Bin (Windows) ---------------------------------------------------
DRIVE_FIXED = 3


def can_recycle(path: Path) -> bool:
    """True only on local fixed drives. USB/SD cards and network drives have no
    Recycle Bin: Windows would delete permanently, so we never offer it there."""
    if os.name != "nt":
        return False
    return _fixed_drive(os.path.splitdrive(os.path.abspath(path))[0] + "\\")


@lru_cache(maxsize=32)
def _fixed_drive(root: str) -> bool:
    if root.startswith("\\\\"):
        return False  # UNC network path
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(root) == DRIVE_FIXED


def recycle(paths: Sequence[Path]) -> list[Path]:
    """Send files to the Recycle Bin. Returns the paths that could not be recycled."""
    if not paths:
        return []
    allowed = [p for p in paths if can_recycle(p)]
    allowed_set = set(allowed)
    refused = [p for p in paths if p not in allowed_set]
    if allowed:
        _shell_recycle(allowed)
    return refused + [p for p in allowed if p.exists()]


def _shell_recycle(paths: Sequence[Path]) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x0004, 0x0010, 0x0040
    FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x0400, 0x4000
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    # Double-NUL-terminated list of absolute paths.
    op.pFrom = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
    # ALLOWUNDO = Recycle Bin; WANTNUKEWARNING makes Windows ask instead of
    # silently deleting if a file somehow cannot be recycled.
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
