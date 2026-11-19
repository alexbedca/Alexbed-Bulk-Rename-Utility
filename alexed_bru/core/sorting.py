# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Order the file list by name, folder or tags, so counters (01, 02, ...) follow that order.

Pure: reads names and metadata, never changes files. Files without the tag keep their
relative order and go last (in either direction), so a few untagged files never scatter.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Callable, Sequence

from alexed_bru.core.models import FileItem, split_name

SORTS = [("name", "Name"), ("folder", "Folder, then name"), ("taken", "Date taken (photos, videos)"),
         ("track", "Track number (disc, then track)"), ("size", "File size"), ("modified", "Date modified")]
NEEDS = {"taken": {"exif", "video", "sys"}, "track": {"audio"}, "size": {"sys"}, "modified": {"sys"}}


def _natural(text: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def _name(item: FileItem):
    stem, ext = split_name(item.name)
    return (_natural(stem), _natural(ext))


def _value(key: str, item: FileItem, meta: Callable[[FileItem, str], dict | None]):
    """The value to sort by, or None when the file doesn't have it."""
    if key == "taken":
        for ns in ("exif", "video"):
            date = (meta(item, ns) or {}).get("date")
            if isinstance(date, datetime):
                return date.replace(tzinfo=None)
        return (meta(item, "sys") or {}).get("modified")  # no date taken: when the file was made/changed
    if key == "track":
        tags = meta(item, "audio") or {}
        track = tags.get("track")
        return None if track is None else (tags.get("disc") or 0, track)
    if key in ("size", "modified"):
        return (meta(item, "sys") or {}).get(key)
    return None


def order(items: Sequence[FileItem], key: str, meta: Callable[[FileItem, str], dict | None],
          reverse: bool = False) -> list[int]:
    """Indices of `items` in the new order."""
    idx = list(range(len(items)))
    if key == "name":
        return sorted(idx, key=lambda i: _name(items[i]), reverse=reverse)
    if key == "folder":
        return sorted(idx, key=lambda i: (_natural(items[i].folder_key), _name(items[i])), reverse=reverse)
    values = {i: _value(key, items[i], meta) for i in idx}
    have = sorted((i for i in idx if values[i] is not None),
                  key=lambda i: (values[i], _name(items[i])), reverse=reverse)
    return have + [i for i in idx if values[i] is None]
