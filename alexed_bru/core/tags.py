# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dynamic tag expansion: ``<audio:artist> - <audio:title>``.

Grammar:  ``<head>``  |  ``<head:key>``  |  ``<head:key:format>``

Built-in heads with no namespace:
    <name>        original file name without extension
    <ext>         original extension
    <folder>      parent folder name
    <num>         1-based position in the batch, <num:3> pads to 3 digits
    <fnum>        1-based position within its folder, <fnum:2> pads

Namespaced heads (``sys``, ``audio``, ``doc``, ``exif``, ...) are served by
metadata providers. A format applies to dates (strftime) and to numbers
(zero-pad width). Tag values are sanitised so they never inject path
separators or other illegal characters.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alexed_bru.core.pipeline import RuleContext

# (?<!\\g) keeps regex back-references like \g<name> intact.
TAG_RE = re.compile(r"(?<!\\g)<([a-z]+)(?::([A-Za-z0-9_]+))?(?::([^<>]*))?>")

_SANITISE = str.maketrans({"/": "-", "\\": "-", "|": "-", ":": " -", "*": "", "?": "",
                           '"': "'", "<": "(", ">": ")", "\t": " ", "\n": " ", "\r": ""})

BUILTIN_HEADS = {"name", "ext", "folder", "num", "fnum"}

# "Smart" short tags: <artist>, <title>, <date> ... Each resolves through an
# ordered fallback chain of (namespace, key) sources, so the same preset
# works on an MP3 (audio tags), a PDF (document info) or a bare file
# (system dates).
SMART_ALIASES: dict[str, list[tuple[str, str]]] = {
    "artist": [("audio", "artist"), ("audio", "albumartist"), ("video", "artist"), ("doc", "author")],
    "albumartist": [("audio", "albumartist"), ("audio", "artist")],
    "album": [("audio", "album"), ("video", "album")],
    "title": [("audio", "title"), ("video", "title"), ("doc", "title")],
    "track": [("audio", "track"), ("video", "track")],
    "disc": [("audio", "disc")],
    "genre": [("audio", "genre"), ("video", "genre")],
    "year": [("audio", "year"), ("video", "year"), ("exif", "year"), ("doc", "year"), ("sys", "created_year")],
    "date": [("exif", "date"), ("video", "date"), ("doc", "created"), ("sys", "created")],
    "created": [("sys", "created")],
    "modified": [("sys", "modified")],
    "author": [("doc", "author"), ("audio", "artist")],
    "duration": [("video", "duration"), ("audio", "duration")],
    "resolution": [("video", "resolution"), ("exif", "resolution")],
    "quality": [("video", "quality")],
    "show": [("video", "show")],
    "season": [("video", "season")],
    "episode": [("video", "episode")],
}


def sanitise(value: str) -> str:
    return value.translate(_SANITISE).strip()


def namespaces_in(text: str) -> set[str]:
    """Metadata namespaces a template needs (so only those get loaded)."""
    found: set[str] = set()
    for m in TAG_RE.finditer(text or ""):
        head = m.group(1)
        if head in BUILTIN_HEADS:
            continue
        if head in SMART_ALIASES:
            found.update(ns for ns, _ in SMART_ALIASES[head])
        else:
            found.add(head)
    return found


def _resolve_alias(head: str, fmt: str | None, ctx: "RuleContext") -> str:
    for ns, key in SMART_ALIASES[head]:
        data = ctx.metadata(ns)
        if data:
            value = data.get(key)
            if value not in (None, ""):
                return sanitise(format_value(value, fmt))
    ctx.warn(f"No value for <{head}>")
    return ""


def format_value(value: Any, fmt: str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime(fmt or "%Y-%m-%d")
    if isinstance(value, int) and not isinstance(value, bool):
        if fmt and fmt.isdigit():
            return str(value).zfill(int(fmt))
        return str(value)
    text = str(value)
    if fmt and fmt.isdigit() and text.isdigit():
        return text.zfill(int(fmt))
    return text


def expand(template: str, ctx: "RuleContext") -> str:
    if "<" not in template:
        return template

    def repl(m: re.Match[str]) -> str:
        head, key, fmt = m.group(1), m.group(2), m.group(3)
        if head in BUILTIN_HEADS:
            # For built-ins the "key" slot doubles as the format (e.g. <num:3>).
            return _builtin(head, fmt or key, ctx)
        if head in SMART_ALIASES:
            return _resolve_alias(head, fmt or key, ctx)
        if key is None:
            return m.group(0)
        data = ctx.metadata(head)
        if data is None:  # unknown namespace: leave visible so validation flags it
            return m.group(0)
        value = data.get(key)
        if value in (None, ""):
            ctx.warn(f"Missing tag <{head}:{key}>")
            return ""
        return sanitise(format_value(value, fmt))

    return TAG_RE.sub(repl, template)


def _builtin(head: str, fmt: str | None, ctx: "RuleContext") -> str:
    if head == "name":
        return ctx.item.stem
    if head == "ext":
        return ctx.item.ext
    if head == "folder":
        return os.path.basename(ctx.item.folder_key)
    if head == "num":
        return format_value(ctx.index + 1, fmt)
    if head == "fnum":
        return format_value(ctx.folder_index + 1, fmt)
    return ""


# Catalogue shown by the UI's tag picker: (tag, description)
TAG_CATALOGUE: list[tuple[str, list[tuple[str, str]]]] = [
    ("Basic", [
        ("<name>", "Original name (no extension)"),
        ("<ext>", "Original extension"),
        ("<folder>", "Parent folder name"),
        ("<num:3>", "Batch position, padded"),
        ("<fnum:2>", "Position within folder, padded"),
    ]),
    ("Smart (auto-fallback)", [
        ("<artist>", "Artist → album artist → document author"),
        ("<album>", "Album"),
        ("<title>", "Audio title → document title"),
        ("<track:2>", "Track number, padded"),
        ("<year>", "Audio year → EXIF → document → file created"),
        ("<date:%Y-%m-%d>", "EXIF taken → document created → file created"),
        ("<created:%Y-%m-%d>", "File created"),
        ("<modified:%Y-%m-%d>", "File modified"),
    ]),
    ("Video", [
        ("<video:title>", "Title"),
        ("<show>", "TV show"),
        ("S<season:2>E<episode:2>", "Season/episode, padded"),
        ("<quality>", "1080p, 720p, ..."),
        ("<resolution>", "Width x height"),
        ("<duration>", "Duration (m.ss)"),
        ("<video:year>", "Year"),
    ]),
    ("System", [
        ("<sys:modified:%Y-%m-%d>", "Modified date"),
        ("<sys:created:%Y-%m-%d>", "Created date"),
        ("<sys:size_kb>", "Size in KB"),
        ("<sys:size_mb>", "Size in MB"),
        ("<sys:parent>", "Parent folder"),
        ("<sys:grandparent>", "Grandparent folder"),
    ]),
    ("Audio", [
        ("<audio:artist>", "Artist"),
        ("<audio:albumartist>", "Album artist"),
        ("<audio:album>", "Album"),
        ("<audio:title>", "Title"),
        ("<audio:track:2>", "Track number, padded"),
        ("<audio:disc>", "Disc number"),
        ("<audio:year>", "Year"),
        ("<audio:genre>", "Genre"),
        ("<audio:composer>", "Composer"),
        ("<audio:bitrate>", "Bitrate (kbps)"),
        ("<audio:duration>", "Duration (m.ss)"),
    ]),
    ("Document", [
        ("<doc:title>", "Title"),
        ("<doc:author>", "Author"),
        ("<doc:subject>", "Subject"),
        ("<doc:created:%Y-%m-%d>", "Created date"),
        ("<doc:modified:%Y-%m-%d>", "Modified date"),
        ("<doc:pages>", "Page count (PDF)"),
    ]),
    ("Image (EXIF)", [
        ("<exif:date:%Y-%m-%d_%H%M%S>", "Date taken"),
        ("<exif:make>", "Camera make"),
        ("<exif:model>", "Camera model"),
        ("<exif:width>", "Width px"),
        ("<exif:height>", "Height px"),
        ("<exif:iso>", "ISO"),
    ]),
]
