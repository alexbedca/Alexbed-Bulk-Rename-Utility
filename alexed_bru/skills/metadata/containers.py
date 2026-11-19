# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small pure-Python tag readers for Matroska (MKV/WebM) and AVI (RIFF). No external tools.

Both return the same keys as the MP4 reader (title, artist, year, date, genre, comment, show,
season, episode, track, duration, seconds, width, height) or {} for anything they can't read.
They only read headers: the video data itself is skipped by seeking, never loaded, and every
size read from the file is checked against the file size, so corrupt or cut-off files give
fewer (or no) tags instead of an error.
"""
from __future__ import annotations

import os
import re
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Iterator

MAX_ELEMENTS = 20000          # guard against loops in corrupt files
MAX_TEXT = 64 * 1024          # a tag value larger than this is not a name worth using

# ---------------------------------------------------------------------- Matroska / EBML
EBML, SEGMENT = 0x1A45DFA3, 0x18538067
SEEKHEAD, SEEK, SEEK_ID, SEEK_POS = 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, TIMESCALE, DURATION, TITLE, DATE_UTC = 0x1549A966, 0x2AD7B1, 0x4489, 0x7BA9, 0x4461
TRACKS, TRACK_ENTRY, TRACK_TYPE, VIDEO, PIXEL_W, PIXEL_H = 0x1654AE6B, 0xAE, 0x83, 0xE0, 0xB0, 0xBA
TAGS, TAG, TARGETS, TARGET_TYPE_VALUE = 0x1254C367, 0x7373, 0x63C0, 0x68CA
TARGET_UIDS = {0x63C5, 0x63C9, 0x63C4, 0x63C6}   # tag applies to one track/edition/chapter/attachment
SIMPLE_TAG, TAG_NAME, TAG_STRING = 0x67C8, 0x45A3, 0x4487
CLUSTER = 0x1F43B675
UNKNOWN = -1
EPOCH_2001 = datetime(2001, 1, 1)


def _vint(fh: BinaryIO, keep_marker: bool) -> int | None:
    """An EBML variable-length integer: element IDs keep their length marker, sizes don't."""
    first = fh.read(1)
    if not first:
        return None
    b = first[0]
    length = 1
    while length <= 8 and not b & (0x80 >> (length - 1)):
        length += 1
    if length > 8:
        return None
    rest = fh.read(length - 1)
    if len(rest) != length - 1:
        return None
    value = b if keep_marker else b & (0xFF >> length)
    for x in rest:
        value = (value << 8) | x
    if not keep_marker and value == (1 << (7 * length)) - 1:
        return UNKNOWN  # "size unknown" (live streams): the element runs to its parent's end
    return value


def _elements(fh: BinaryIO, start: int, end: int, budget: list[int]) -> Iterator[tuple[int, int, int]]:
    """Yield (id, data_start, data_end) for the elements in [start, end)."""
    pos = start
    while pos < end and budget[0] > 0:
        budget[0] -= 1
        fh.seek(pos)
        eid = _vint(fh, keep_marker=True)
        size = _vint(fh, keep_marker=False)
        if eid is None or size is None:
            return
        data = fh.tell()
        stop = end if size == UNKNOWN else data + size
        if stop > end:
            stop = end  # cut-off file: read what is there
        yield eid, data, stop
        if size == UNKNOWN:
            return  # can't skip it: nothing after it can be found by walking
        pos = stop


def _uint(fh: BinaryIO, start: int, end: int) -> int:
    fh.seek(start)
    raw = fh.read(min(end - start, 8))
    return int.from_bytes(raw, "big") if raw else 0


def _sint(fh: BinaryIO, start: int, end: int) -> int:
    fh.seek(start)
    raw = fh.read(min(end - start, 8))
    return int.from_bytes(raw, "big", signed=True) if raw else 0


def _float(fh: BinaryIO, start: int, end: int) -> float | None:
    fh.seek(start)
    raw = fh.read(end - start)
    if len(raw) == 4:
        return struct.unpack(">f", raw)[0]
    if len(raw) == 8:
        return struct.unpack(">d", raw)[0]
    return None


def _text(fh: BinaryIO, start: int, end: int) -> str:
    if end - start > MAX_TEXT:
        return ""
    fh.seek(start)
    return fh.read(end - start).split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


def read_matroska(path: Path) -> dict:
    """Title, tags, duration and video size from an MKV/MKA/WebM file ({} if it isn't one)."""
    with open(path, "rb") as fh:
        return matroska_tags(fh, os.fstat(fh.fileno()).st_size)


def matroska_tags(fh: BinaryIO, size: int) -> dict:
    """read_matroska on an open binary file of `size` bytes."""
    out: dict = {}
    budget = [MAX_ELEMENTS]
    first = next(_elements(fh, 0, size, budget), None)
    if first is None or first[0] != EBML:
        return {}
    segment = next(((s, e) for i, s, e in _elements(fh, first[2], size, budget) if i == SEGMENT), None)
    if segment is None:
        return {}
    seg_start, seg_end = segment
    sections: dict[int, int] = {}       # where Info/Tracks/Tags start (from walking or the SeekHead)
    done: set[int] = set()
    tags: list[tuple[int, str, str]] = []
    info: dict = {}

    def read_section(eid: int, s: int, e: int) -> None:
        done.add(s)
        if eid == SEEKHEAD:
            for sid, ss, se in _elements(fh, s, e, budget):
                if sid != SEEK:
                    continue
                target = position = None
                for kid, ks, ke in _elements(fh, ss, se, budget):
                    if kid == SEEK_ID:
                        target = _uint(fh, ks, ke)
                    elif kid == SEEK_POS:
                        position = seg_start + _uint(fh, ks, ke)
                if target in (INFO, TRACKS, TAGS) and position is not None and position < seg_end:
                    sections.setdefault(position, target)
        elif eid == INFO:
            _matroska_info(fh, s, e, budget, info)
        elif eid == TRACKS:
            _matroska_tracks(fh, s, e, budget, info)
        elif eid == TAGS:
            _matroska_tags(fh, s, e, budget, tags)

    # Walk the top level up to the first Cluster (the video data), then jump to anything the
    # SeekHead says lies further on (ffmpeg and others often write Tags at the end).
    for eid, s, e in _elements(fh, seg_start, seg_end, budget):
        if eid == CLUSTER:
            break
        if eid in (SEEKHEAD, INFO, TRACKS, TAGS):
            read_section(eid, s, e)
    for position, target in sorted(sections.items()):
        hit = next(_elements(fh, position, seg_end, budget), None)
        if hit and hit[0] == target and hit[1] not in done:
            read_section(*hit)

    out.update({k: v for k, v in info.items() if k in ("title", "width", "height")})
    if "duration_ns" in info:
        out["seconds_f"] = info["duration_ns"] / 1e9
    if "date_utc" in info:
        out["date"] = info["date_utc"]
    for target, name, value in tags:
        if not value:
            continue
        if name == "TITLE":
            key = "show" if target >= 70 else ("title" if target >= 50 else "track_title")
        elif name == "PART_NUMBER":
            key = "season" if 60 <= target < 70 else ("episode" if target >= 50 else "track")
            if key == "episode":
                out.setdefault("track", value)
        else:
            key = _MKV_NAMES.get(name)
        if key:
            out.setdefault(key, value)
    if "title" not in out and "track_title" in out:
        out["title"] = out["track_title"]
    out.pop("track_title", None)
    if "seconds_f" not in out and "duration_tag" in out:
        out["seconds_f"] = _hms(out["duration_tag"])
    out.pop("duration_tag", None)
    return _finish(out)


_MKV_NAMES = {"ARTIST": "artist", "LEAD_PERFORMER": "artist", "DIRECTOR": "director", "GENRE": "genre",
              "COMMENT": "comment", "DESCRIPTION": "description", "SUMMARY": "description",
              "DATE_RELEASED": "date_raw", "DATE_RECORDED": "date_raw", "DATE": "date_raw",
              "DATE_ENCODED": "date_raw", "YEAR": "date_raw", "DURATION": "duration_tag",
              "ALBUM": "album"}


def _matroska_info(fh, s, e, budget, info: dict) -> None:
    scale, duration = 1_000_000, None
    for kid, ks, ke in _elements(fh, s, e, budget):
        if kid == TIMESCALE:
            scale = _uint(fh, ks, ke) or 1_000_000
        elif kid == DURATION:
            duration = _float(fh, ks, ke)
        elif kid == TITLE:
            info["title"] = _text(fh, ks, ke)
        elif kid == DATE_UTC:
            try:
                info["date_utc"] = EPOCH_2001 + timedelta(microseconds=_sint(fh, ks, ke) // 1000)
            except OverflowError:
                pass
    if duration and duration > 0 and duration == duration:  # not NaN
        info["duration_ns"] = duration * scale


def _matroska_tracks(fh, s, e, budget, info: dict) -> None:
    for tid, ts, te in _elements(fh, s, e, budget):
        if tid != TRACK_ENTRY:
            continue
        kind, w, h = None, 0, 0
        for kid, ks, ke in _elements(fh, ts, te, budget):
            if kid == TRACK_TYPE:
                kind = _uint(fh, ks, ke)
            elif kid == VIDEO:
                for vid, vs, ve in _elements(fh, ks, ke, budget):
                    if vid == PIXEL_W:
                        w = _uint(fh, vs, ve)
                    elif vid == PIXEL_H:
                        h = _uint(fh, vs, ve)
        if kind == 1 and w and h and w * h > info.get("width", 0) * info.get("height", 0):
            info["width"], info["height"] = w, h


def _matroska_tags(fh, s, e, budget, tags: list) -> None:
    """Collect (target type, NAME, value) from tags that apply to the whole file."""
    for tid, ts, te in _elements(fh, s, e, budget):
        if tid != TAG:
            continue
        target, per_item, simple = 50, False, []
        for kid, ks, ke in _elements(fh, ts, te, budget):
            if kid == TARGETS:
                for gid, gs, ge in _elements(fh, ks, ke, budget):
                    if gid == TARGET_TYPE_VALUE:
                        target = _uint(fh, gs, ge)
                    elif gid in TARGET_UIDS and _uint(fh, gs, ge):
                        per_item = True   # e.g. ffmpeg's per-track ENCODER/DURATION
            elif kid == SIMPLE_TAG:
                simple.append((ks, ke))
        for ks, ke in simple:
            name = value = ""
            for kid, vs, ve in _elements(fh, ks, ke, budget):
                if kid == TAG_NAME:
                    name = _text(fh, vs, ve).upper()
                elif kid == TAG_STRING:
                    value = _text(fh, vs, ve)
            if per_item and name != "DURATION":
                continue
            tags.append((target, name, value))


def _hms(text: str) -> float | None:
    m = re.match(r"\s*(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)", text or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


# ---------------------------------------------------------------------- AVI / RIFF
_AVI_INFO = {b"INAM": "title", b"IART": "artist", b"ICRD": "date_raw", b"IGNR": "genre",
             b"ICMT": "comment", b"ISBJ": "description", b"IPRT": "track", b"ITRK": "track",
             b"IPRD": "album", b"ISFT": "software"}


def _chunks(fh: BinaryIO, start: int, end: int, budget: list[int]) -> Iterator[tuple[bytes, int, int]]:
    """Yield (fourcc, data_start, data_end) for RIFF chunks in [start, end); sizes are padded to even."""
    pos = start
    while pos + 8 <= end and budget[0] > 0:
        budget[0] -= 1
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return
        fourcc, size = head[:4], struct.unpack("<I", head[4:])[0]
        data = pos + 8
        stop = min(data + size, end)
        yield fourcc, data, stop
        pos = data + size + (size & 1)


def read_avi(path: Path) -> dict:
    """INFO tags, duration and frame size from an AVI file ({} if it isn't one)."""
    with open(path, "rb") as fh:
        return avi_tags(fh, os.fstat(fh.fileno()).st_size)


def avi_tags(fh: BinaryIO, size: int) -> dict:
    """read_avi on an open binary file of `size` bytes."""
    out: dict = {}
    head = fh.read(12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"AVI ":
        return {}
    riff_end = min(8 + struct.unpack("<I", head[4:8])[0], size)
    budget = [MAX_ELEMENTS]
    for fourcc, s, e in _chunks(fh, 12, riff_end, budget):
        if fourcc != b"LIST" or e - s < 4:
            continue           # 'movi' data, 'idx1' index, JUNK: skipped without reading
        fh.seek(s)
        kind = fh.read(4)
        if kind == b"hdrl":
            for cid, cs, ce in _chunks(fh, s + 4, e, budget):
                if cid == b"avih" and ce - cs >= 40:
                    fh.seek(cs)
                    (us_per_frame, _rate, _pad, _flags, frames, _init, _streams, _buf,
                     width, height) = struct.unpack("<10I", fh.read(40))
                    if us_per_frame and frames:
                        out["seconds_f"] = us_per_frame * frames / 1e6
                    if width and height:
                        out["width"], out["height"] = width, height
                    break
        elif kind == b"INFO":
            for cid, cs, ce in _chunks(fh, s + 4, e, budget):
                key = _AVI_INFO.get(cid)
                if key and ce - cs <= MAX_TEXT:
                    fh.seek(cs)
                    raw = fh.read(ce - cs).split(b"\x00", 1)[0]
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw.decode("cp1252", "replace")
                    if text.strip():
                        out.setdefault(key, text.strip())
    return _finish(out)


# ---------------------------------------------------------------------- shared
def _finish(out: dict) -> dict:
    """Turn raw values into the same keys/types the MP4 reader gives."""
    raw_date = out.pop("date_raw", None)
    if raw_date and "date" not in out:
        out["date"] = _parse_date(raw_date)
    if isinstance(out.get("date"), datetime):
        out["year"] = out["date"].year
    elif raw_date:
        m = re.search(r"\b(1[89]\d\d|2\d\d\d)\b", raw_date)
        if m:
            out["year"] = int(m.group(1))
    for key in ("track", "episode", "season"):
        if key in out:
            m = re.match(r"\s*(\d+)", str(out[key]))
            out[key] = int(m.group(1)) if m else None
    seconds = out.pop("seconds_f", None)
    if seconds and 0 < seconds < 10 * 365 * 86400:
        total = int(seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        out["duration"] = f"{h}.{m:02d}.{s:02d}" if h else f"{m}.{s:02d}"
        out["seconds"] = total
    return {k: v for k, v in out.items() if v not in (None, "")}


def _parse_date(text: str) -> datetime | None:
    """'2019-05-01', '2019-05-01T10:20:30Z', '2019', or 'Wed Jan 02 02:03:55 1990' (some AVI writers)."""
    text = text.strip()
    for fmt, length in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10),
                        ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
