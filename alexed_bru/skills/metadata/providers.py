"""Built-in metadata providers: sys, audio, doc, exif."""
from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
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
            "make": str(exif.get(0x010F, "")).strip("\x00 "),
            "model": str(exif.get(0x0110, "")).strip("\x00 "),
            "iso": sub.get(0x8827),
            "date": taken,
            "year": taken.year if taken else None,
        }
        return {k: v for k, v in data.items() if v not in (None, "")}
