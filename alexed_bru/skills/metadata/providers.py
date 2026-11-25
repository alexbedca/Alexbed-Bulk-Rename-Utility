# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in metadata providers: sys, audio, doc, exif."""
from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from struct import error as struct_error
from xml.etree import ElementTree as ET

from alexed_bru.skills.metadata import MetaDict, MetadataProvider, register_provider


def _first_int(value) -> int | None:
    """'3/12' -> 3, '2019-05-01' -> 2019, None -> None."""
    if value is None:
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _human_size(num: int, unit: int) -> str:
    return f"{num / unit:.1f}" if num / unit < 100 else str(round(num / unit))


# --------------------------------------------------------------------------
@register_provider
class SystemProvider(MetadataProvider):
    namespace = "sys"
    label = "System"

    def read(self, path: Path) -> MetaDict:
        st = path.stat()
        # st_birthtime exists on Windows (3.12+) and macOS; ctime is creation on older Windows.
        created_ts = getattr(st, "st_birthtime", None) or (st.st_ctime if os.name == "nt" else st.st_mtime)
        created = datetime.fromtimestamp(created_ts)
        modified = datetime.fromtimestamp(st.st_mtime)
        return {
            "created": created,
            "created_year": created.year,
            "modified": modified,
            "accessed": datetime.fromtimestamp(st.st_atime),
            "size": st.st_size,
            "size_kb": _human_size(st.st_size, 1024),
            "size_mb": _human_size(st.st_size, 1024 * 1024),
            "parent": path.parent.name,
            "grandparent": path.parent.parent.name,
            "ext": path.suffix[1:],
            "name": path.stem,
        }


# --------------------------------------------------------------------------
@register_provider
class AudioProvider(MetadataProvider):
    """ID3v1/ID3v2 (MP3), Vorbis comments (FLAC/OGG/Opus), MP4 atoms, APE, ASF."""

    namespace = "audio"
    label = "Audio"
    extensions = frozenset({"mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "mp4", "aac", "alac",
                            "wma", "asf", "wav", "aif", "aiff", "ape", "wv", "mpc", "dsf", "tta"})

    def read(self, path: Path) -> MetaDict:
        import mutagen  # local import keeps app start-up fast

        # easy=True normalises ID3 frames, Vorbis comments and MP4 atoms to the
        # same keys ('artist', 'tracknumber', ...). ID3v1 is read if no v2 tag.
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return {}
        tags = audio.tags or {}

        def tag(key: str) -> str:
            try:
                values = tags.get(key)
            except (KeyError, ValueError):
                return ""
            if not values:
                return ""
            return str(values[0] if isinstance(values, list) else values).strip()

        data: MetaDict = {
            "artist": tag("artist"),
            "albumartist": tag("albumartist") or tag("album artist"),
            "album": tag("album"),
            "title": tag("title"),
            "genre": tag("genre"),
            "composer": tag("composer"),
            "track": _first_int(tag("tracknumber")),
            "tracktotal": _first_int(tag("tracknumber").partition("/")[2] or tag("tracktotal")),
            "disc": _first_int(tag("discnumber")),
            "year": _first_int(tag("date") or tag("year") or tag("originaldate")),
        }
        info = getattr(audio, "info", None)
        if info is not None:
            length = getattr(info, "length", 0) or 0
            data["duration"] = f"{int(length // 60)}.{int(length % 60):02d}"
            bitrate = getattr(info, "bitrate", 0) or 0
            data["bitrate"] = round(bitrate / 1000) if bitrate else None
            data["samplerate"] = getattr(info, "sample_rate", None)
        return {k: v for k, v in data.items() if v not in (None, "")}


# --------------------------------------------------------------------------
_PDF_DATE = re.compile(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")


def _pdf_date(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    m = _PDF_DATE.match(str(raw or ""))
    if not m:
        return None
    parts = [int(p) if p else d for p, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
    try:
        return datetime(*parts)
    except ValueError:
        return None


def _iso_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


_OOXML_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}


@register_provider
class DocumentProvider(MetadataProvider):
    """PDF document info and Office Open XML core properties."""

    namespace = "doc"
    label = "Document"
    OFFICE = frozenset({"docx", "docm", "dotx", "xlsx", "xlsm", "pptx", "pptm", "vsdx"})
    extensions = OFFICE | {"pdf"}

    def read(self, path: Path) -> MetaDict:
        ext = path.suffix[1:].lower()
        data = self._pdf(path) if ext == "pdf" else self._office(path)
        created = data.get("created")
        if isinstance(created, datetime):
            data["year"] = created.year
        return {k: v for k, v in data.items() if v not in (None, "")}

    @staticmethod
    def _pdf(path: Path) -> MetaDict:
        from pypdf import PdfReader

        reader = PdfReader(path)
        info = reader.metadata or {}
        return {
            "title": str(info.get("/Title") or "").strip(),
            "author": str(info.get("/Author") or "").strip(),
            "subject": str(info.get("/Subject") or "").strip(),
            "keywords": str(info.get("/Keywords") or "").strip(),
            "creator": str(info.get("/Creator") or "").strip(),
            "producer": str(info.get("/Producer") or "").strip(),
            "created": _pdf_date(info.get("/CreationDate")),
            "modified": _pdf_date(info.get("/ModDate")),
            "pages": len(reader.pages),
        }

    @staticmethod
    def _office(path: Path) -> MetaDict:
        with zipfile.ZipFile(path) as zf:
            try:
                root = ET.fromstring(zf.read("docProps/core.xml"))
            except KeyError:
                return {}

        def text(tag: str) -> str:
            node = root.find(tag, _OOXML_NS)
            return (node.text or "").strip() if node is not None else ""

        return {
            "title": text("dc:title"),
            "author": text("dc:creator"),
            "subject": text("dc:subject"),
            "keywords": text("cp:keywords"),
            "lastmodifiedby": text("cp:lastModifiedBy"),
            "revision": _first_int(text("cp:revision")),
            "created": _iso_date(text("dcterms:created")),
            "modified": _iso_date(text("dcterms:modified")),
        }


# --------------------------------------------------------------------------
@register_provider
class ExifProvider(MetadataProvider):
    namespace = "exif"
    label = "Image"
    extensions = frozenset({"jpg", "jpeg", "jpe", "tif", "tiff", "png", "webp", "heic", "dng"})

    def read(self, path: Path) -> MetaDict:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
        sub = exif.get_ifd(0x8769) if exif else {}
        raw_date = sub.get(0x9003) or sub.get(0x9004) or exif.get(0x0132)  # Original, Digitized, DateTime
        taken = None
        if raw_date:
            try:
                taken = datetime.strptime(str(raw_date).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                taken = None
        data: MetaDict = {
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}",
            "make": str(exif.get(0x010F, "")).strip("\x00 "),
            "model": str(exif.get(0x0110, "")).strip("\x00 "),
            "iso": sub.get(0x8827),
            "date": taken,
            "year": taken.year if taken else None,
        }
        return {k: v for k, v in data.items() if v not in (None, "")}


# --------------------------------------------------------------------------
def _mp4_boxes(fh, start: int, end: int):
    """Yield (type, payload_start, box_end) for ISO-BMFF boxes in [start, end)."""
    import struct

    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        payload = pos + 8
        if size == 1:  # 64-bit size
            size = struct.unpack(">Q", fh.read(8))[0]
            payload += 8
        elif size == 0:  # box runs to end of file
            size = end - pos
        if size < 8:
            return
        yield kind.decode("latin-1"), payload, pos + size
        pos += size


def _mp4_dimensions(path: Path) -> tuple[int, int] | None:
    """Largest track width/height from moov/trak/tkhd (no external tools)."""
    import struct

    best = None
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        file_end = fh.tell()
        for kind, start, end in _mp4_boxes(fh, 0, file_end):
            if kind != "moov":
                continue
            for tkind, tstart, tend in _mp4_boxes(fh, start, end):
                if tkind != "trak":
                    continue
                for hkind, hstart, _hend in _mp4_boxes(fh, tstart, tend):
                    if hkind != "tkhd":
                        continue
                    fh.seek(hstart)
                    version = fh.read(1)[0]
                    fh.seek(hstart + (84 if version == 1 else 72) + 4)  # width/height are last 8 bytes
                    w, h = struct.unpack(">II", fh.read(8))
                    w, h = w >> 16, h >> 16  # 16.16 fixed point
                    if w and h and (best is None or w * h > best[0] * best[1]):
                        best = (w, h)
    return best


_QT_TEXT = {"©nam": "title", "©ART": "artist", "©aut": "artist", "©day": "date_raw",
            "©des": "description", "©cmt": "comment", "©mak": "make", "©mod": "model",
            "©swr": "software"}
_MDTA = {"com.apple.quicktime.title": "title", "com.apple.quicktime.artist": "artist",
         "com.apple.quicktime.creationdate": "date_raw", "com.apple.quicktime.make": "make",
         "com.apple.quicktime.model": "model", "com.apple.quicktime.description": "description",
         "com.apple.quicktime.software": "software", "title": "title", "artist": "artist",
         "date": "date_raw", "creation_time": "date_raw"}


def _quicktime_tags(path: Path) -> MetaDict:
    """QuickTime metadata mutagen doesn't read: moov/udta (c)xxx atoms and Apple 'mdta' keys
    (what iPhones write: creation date, make, model)."""
    import struct

    out: MetaDict = {}
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        file_end = fh.tell()
        moov = next(((s, e) for k, s, e in _mp4_boxes(fh, 0, file_end) if k == "moov"), None)
        if moov is None:
            return out
        def parse_meta(start: int, end: int) -> None:
            # ISO 'meta' starts with 4 zero bytes (version/flags); QuickTime 'meta'
            # starts directly with a child box, whose size is never zero.
            fh.seek(start)
            body = start + 4 if fh.read(4) == b"\x00\x00\x00\x00" else start
            children = list(_mp4_boxes(fh, body, end))
            keys: list[str] = []
            for k, s, e in children:
                if k == "keys":
                    fh.seek(s + 4)
                    count = struct.unpack(">I", fh.read(4))[0]
                    for _ in range(min(count, 512)):
                        size, _ns = struct.unpack(">I4s", fh.read(8))
                        keys.append(fh.read(max(0, size - 8)).decode("utf-8", "replace"))
            for k, s, e in children:
                if k != "ilst" or not keys:
                    continue  # iTunes-style ilst (no keys) is mutagen's job
                pos = s
                while pos + 8 <= e:
                    fh.seek(pos)
                    size, idx = struct.unpack(">II", fh.read(8))
                    if size < 8:
                        break
                    if 1 <= idx <= len(keys) and keys[idx - 1] in _MDTA:
                        for dk, ds, de in _mp4_boxes(fh, pos + 8, pos + size):
                            if dk == "data" and de - ds > 8:
                                fh.seek(ds)
                                dtype = struct.unpack(">I", fh.read(4))[0] & 0xFFFFFF
                                fh.read(4)  # locale
                                raw = fh.read(de - ds - 8)
                                if dtype in (1, 4):  # UTF-8 / UTF-16 text
                                    text = raw.decode("utf-8" if dtype == 1 else "utf-16-be", "replace")
                                    out.setdefault(_MDTA[keys[idx - 1]], text.strip("\x00 "))
                    pos += size

        for kind, start, end in list(_mp4_boxes(fh, *moov)):
            if kind == "meta":            # iPhone: moov/meta
                parse_meta(start, end)
            elif kind == "udta":
                for k, s, e in list(_mp4_boxes(fh, start, end)):
                    if k == "meta":       # ffmpeg & others: moov/udta/meta
                        parse_meta(s, e)
                    elif k in _QT_TEXT and e - s > 4:
                        fh.seek(s)
                        n, _lang = struct.unpack(">HH", fh.read(4))
                        if 0 < n <= e - s - 4:  # QuickTime text atom
                            out.setdefault(_QT_TEXT[k], fh.read(n).decode("utf-8", "replace").strip("\x00 "))
    raw_date = out.pop("date_raw", None)
    if raw_date:
        parsed = _iso_date(raw_date) or (datetime(int(raw_date[:4]), 1, 1) if raw_date[:4].isdigit() else None)
        if parsed:
            out["date"] = parsed
            out["year"] = parsed.year
    return {k: v for k, v in out.items() if v not in (None, "")}


@register_provider
class VideoProvider(MetadataProvider):
    """MP4 / M4V / MOV / 3GP: iTunes-style tags; MKV / WebM / AVI: Matroska tags and RIFF INFO.
    All with duration and resolution."""

    namespace = "video"
    label = "Video"
    MATROSKA = frozenset({"mkv", "mk3d", "webm"})
    extensions = frozenset({"mp4", "m4v", "mov", "3gp", "3g2", "avi", "flv", "wmv"}) | MATROSKA

    def read(self, path: Path) -> MetaDict:
        ext = path.suffix[1:].lower()
        if ext in self.MATROSKA or ext in ("avi", "flv", "wmv"):
            from alexed_bru.skills.metadata import containers
            try:
                if ext in self.MATROSKA:
                    data = containers.read_matroska(path)
                elif ext == "avi":
                    data = containers.read_avi(path)
                elif ext == "flv":
                    data = containers.read_flv(path)
                else:
                    data = _wmv_tags(path)
            except (ValueError, struct_error, OverflowError, MemoryError, UnicodeError):
                data = {}  # corrupt or cut off: no tags (OSError still reaches the store, as for MP4)
            if data.get("width") and data.get("height"):
                w, h = data["width"], data["height"]
                data.update(resolution=f"{w}x{h}", quality=_quality(w, h))
            return data
        from mutagen.mp4 import MP4

        data: MetaDict = {}
        try:
            mp4 = MP4(path)
        except Exception:  # noqa: BLE001  (untagged/odd files still get resolution)
            mp4 = None
        if mp4 is not None:
            tags = mp4.tags or {}

            def tag(key: str):
                value = tags.get(key)
                if not value:
                    return None
                v = value[0]
                return v[0] if isinstance(v, tuple) else v  # trkn/disk are (n, total)

            data.update({
                "title": tag("\xa9nam"), "artist": tag("\xa9ART"), "album": tag("\xa9alb"),
                "genre": tag("\xa9gen"), "comment": tag("\xa9cmt"), "description": tag("desc"),
                "show": tag("tvsh"), "season": tag("tvsn"), "episode": tag("tves"),
                "episode_id": tag("tven"), "network": tag("tvnn"),
                "year": _first_int(tag("\xa9day")), "track": tag("trkn"),
            })
            length = getattr(mp4.info, "length", 0) or 0
            if length:
                h, rem = divmod(int(length), 3600)
                m, s = divmod(rem, 60)
                data["duration"] = f"{h}.{m:02d}.{s:02d}" if h else f"{m}.{s:02d}"
                data["seconds"] = int(length)
        try:
            for key, value in _quicktime_tags(path).items():
                if data.get(key) in (None, ""):  # iTunes tags (via mutagen) win
                    data[key] = value
        except (OSError, ValueError, struct_error):
            pass
        dims = _mp4_dimensions(path)
        if dims:
            w, h = dims
            data.update(width=w, height=h, resolution=f"{w}x{h}", quality=_quality(w, h))
        return {k: (str(v).strip() if isinstance(v, str) else v) for k, v in data.items()
                if v not in (None, "")}


def _wmv_tags(path: Path) -> MetaDict:
    """WMV (ASF): tags through mutagen, frame size from the header."""
    from mutagen.asf import ASF, error as asf_error

    from alexed_bru.skills.metadata import containers

    data: MetaDict = {}
    try:
        asf = ASF(path)
    except (asf_error, ValueError, struct_error):
        asf = None
    if asf is not None:
        tags = asf.tags or {}

        def tag(*keys: str) -> str:
            for key in keys:
                values = tags.get(key)
                if values and str(values[0]).strip():
                    return str(values[0]).strip()
            return ""

        raw = {"title": tag("Title", "title"), "artist": tag("Author", "WM/AlbumArtist", "artist"),
               "album": tag("WM/AlbumTitle"), "genre": tag("WM/Genre"), "comment": tag("Description"),
               "date_raw": tag("WM/Year", "date", "WM/OriginalReleaseYear"), "track": tag("WM/TrackNumber"),
               "seconds_f": getattr(asf.info, "length", 0) or None}
        data = {k: v for k, v in raw.items() if v not in (None, "")}
    with path.open("rb") as fh:
        dims = containers.asf_dimensions(fh)
    if dims:
        data["width"], data["height"] = dims
    return containers._finish(data)


def _quality(w: int, h: int) -> str:
    short = min(w, h)
    for limit, label in ((2160, "2160p"), (1440, "1440p"), (1080, "1080p"), (720, "720p"),
                         (576, "576p"), (480, "480p"), (360, "360p")):
        if short >= limit * 0.95:
            return label
    return f"{short}p"
