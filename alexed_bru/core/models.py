# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from pathlib import Path


class Status(enum.IntEnum):
    """Lifecycle of one row. Higher values are more severe (except SUCCESS)."""

    UNCHANGED = 0   # rules produce the same name; nothing to do
    PENDING = 1     # valid new name, waiting for Apply
    WARNING = 2     # will be applied, but something deserves attention (missing tag...)
    ERROR = 3       # invalid name or collision; will be skipped
    SUCCESS = 4     # renamed on disk by the last Apply

    @property
    def label(self) -> str:
        return {0: "Unchanged", 1: "Pending", 2: "Warning", 3: "Error", 4: "Renamed"}[self.value]

    @property
    def appliable(self) -> bool:
        return self in (Status.PENDING, Status.WARNING)


class FileItem:
    """One file in the batch. Derived name parts are cached (hot path for 10k+ files)."""

    __slots__ = ("_path", "include", "manual", "name", "stem", "ext", "folder_key", "is_dir")

    def __init__(self, path: Path, include: bool = True, manual: str | None = None,
                 is_dir: bool = False) -> None:
        self.include = include
        self.manual = manual  # a new name typed by hand: used instead of the rules
        self.is_dir = is_dir  # a folder row (folder renaming mode): the whole name is the "stem"
        self.path = path

    @property
    def path(self) -> Path:
        return self._path

    @path.setter
    def path(self, value: Path) -> None:
        # Plain string splitting: pathlib's .name/.parent parse the path again and cost ~25 us
        # each, which froze the window for a second when 20,000 files were added.
        self._path = value if isinstance(value, Path) else Path(value)
        self.folder_key, self.name = os.path.split(str(self._path))
        self.stem, self.ext = (self.name, "") if self.is_dir else split_name(self.name)

    @property
    def folder(self) -> Path:
        return Path(self.folder_key)

    def copy(self) -> "FileItem":
        """A copy for background jobs, without parsing the path again."""
        twin = FileItem.__new__(FileItem)
        for slot in FileItem.__slots__:
            setattr(twin, slot, getattr(self, slot))
        return twin

    def __repr__(self) -> str:
        return f"FileItem({str(self._path)!r}, include={self.include})"


@dataclass(slots=True)
class Proposal:
    new_name: str
    status: Status = Status.UNCHANGED
    messages: list[str] = field(default_factory=list)
    previous: str = ""  # set after Apply: the name the file had before
    manual: bool = False  # the name was typed by hand, not made by the rules

    @property
    def message(self) -> str:
        return "; ".join(self.messages)


def split_name(name: str) -> tuple[str, str]:
    """Split into (stem, ext) where ext excludes the dot.

    Dot-files such as '.gitignore' have no extension, and a trailing dot
    yields an empty extension.
    """
    idx = name.rfind(".")
    if idx <= 0:
        return name, ""
    return name[:idx], name[idx + 1:]


def join_name(stem: str, ext: str) -> str:
    return f"{stem}.{ext}" if ext else stem
