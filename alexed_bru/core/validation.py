# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Name and collision validation, run before anything touches the disk."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Callable, Sequence

from alexed_bru.core.models import FileItem, Proposal, Status, join_name, split_name

INVALID_CHARS = '\\/:*?"<>|'
_INVALID_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME = 255
MAX_PATH_WARN = 259

CASE_INSENSITIVE_FS = os.name == "nt"


def name_errors(name: str) -> list[str]:
    """Problems that make a file name impossible on Windows (and unsafe elsewhere)."""
    errors: list[str] = []
    if not name or not name.strip(". "):
        return ["Name is empty"]
    bad = sorted(set(_INVALID_RE.findall(name)))
    if bad:
        shown = " ".join("\\x%02x" % ord(c) if ord(c) < 32 else c for c in bad)
        errors.append(f"Invalid character(s): {shown}")
    if name.split(".")[0].rstrip(" ").upper() in RESERVED:
        errors.append(f"“{name.split('.')[0]}” is a reserved Windows name")
    if name[-1] in ". ":
        errors.append("Name ends with a dot or space")
    if len(name) > MAX_NAME:
        errors.append(f"Name is {len(name)} characters (max {MAX_NAME})")
    return errors


def fold(name: str) -> str:
    return name.casefold() if CASE_INSENSITIVE_FS else name


class DirectoryLister:
    """Caches folder listings so collision checks on 10k files are fast."""

    def __init__(self) -> None:
        self._cache: dict[str, set[str] | None] = {}

    def names(self, folder: str) -> set[str] | None:
        if folder not in self._cache:
            try:
                self._cache[folder] = {fold(n) for n in os.listdir(folder)}
            except OSError:
                self._cache[folder] = None
        return self._cache[folder]


NUMBERED_NOTE = "Numbered to avoid a duplicate name"


def numbered(name: str, n: int) -> str:
    """'photo.jpg', 2 -> 'photo (2).jpg'."""
    stem, ext = split_name(name)
    return join_name(f"{stem} ({n})", ext)


def _auto_number(items: Sequence[FileItem], proposals: Sequence[Proposal], changing: list[int],
                 moving_away: set[tuple[str, str]], lister: DirectoryLister) -> None:
    """Give clashing new names a free ' (n)' ending, in list order: the first file keeps the name.

    A name is taken if another file in the batch already claimed it, or if a file
    that stays put (not renamed in this batch) already has it on disk.
    """
    claimed: dict[str, set[str]] = defaultdict(set)

    def taken(folder: str, name: str, own: str) -> bool:
        key = fold(name)
        if key in claimed[folder]:
            return True
        if key == own:  # its own current name (e.g. a case-only rename)
            return False
        listing = lister.names(folder)
        return listing is not None and key in listing and (folder, key) not in moving_away

    for i in changing:
        item, prop = items[i], proposals[i]
        folder, own = item.folder_key, fold(item.name)
        if taken(folder, prop.new_name, own):
            n = 1
            while taken(folder, numbered(prop.new_name, n), own):
                n += 1
            prop.new_name = numbered(prop.new_name, n)
            prop.messages.append(NUMBERED_NOTE)
        claimed[folder].add(fold(prop.new_name))


def validate(items: Sequence[FileItem], proposals: Sequence[Proposal],
             lister: DirectoryLister | None = None,
             cancelled: Callable[[], bool] | None = None,
             auto_number: bool = False) -> None:
    """Update proposal status/messages in place.

    With ``auto_number``, clashing names get ' (1)', ' (2)'... instead of an error.
    """
    lister = lister or DirectoryLister()

    changing = [i for i, p in enumerate(proposals)
                if items[i].include and p.status in (Status.PENDING, Status.WARNING)
                and p.new_name != items[i].name]

    # Names that will be vacated by this batch (so their slots are free).
    moving_away = {(items[i].folder_key, fold(items[i].name)) for i in changing}

    if auto_number:
        _auto_number(items, proposals, changing, moving_away, lister)

    # Duplicate targets inside the batch.
    targets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i in changing:
        targets[(items[i].folder_key, fold(proposals[i].new_name))].append(i)

    for n, i in enumerate(changing):
        if cancelled and n % 1000 == 0 and cancelled():
            return
        item, prop = items[i], proposals[i]
        errors = name_errors(prop.new_name)

        key = (item.folder_key, fold(prop.new_name))
        clash = targets[key]
        if len(clash) > 1:
            others = [items[j].name for j in clash if j != i][:3]
            errors.append("Duplicate: same new name as " + ", ".join(others))

        listing = lister.names(item.folder_key)
        if listing is not None:
            if fold(item.name) not in listing:
                errors.append("Source file no longer exists")
            # Same folded key = case-only rename of itself: allowed.
            elif key[1] in listing and key not in moving_away and key[1] != fold(item.name):
                errors.append("A file with this name already exists")

        if errors:
            prop.status = Status.ERROR
            prop.messages = errors + prop.messages
            continue
        if len(item.folder_key) + 1 + len(prop.new_name) > MAX_PATH_WARN:
            prop.messages.append("Full path exceeds 260 characters")
        if prop.new_name.startswith(" "):
            prop.messages.append("Name starts with a space")
        prop.status = Status.WARNING if prop.messages else Status.PENDING
