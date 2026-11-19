"""MKV/WebM (EBML) and AVI (RIFF) tag readers, on tiny files built here (no ffmpeg needed)."""
import struct
from datetime import datetime
from pathlib import Path

import pytest

from alexed_bru.core.engine import RenameEngine
from alexed_bru.skills.metadata import MetadataStore
from alexed_bru.skills.metadata.containers import avi_tags, matroska_tags, read_avi, read_matroska
from alexed_bru.skills.rules import TemplateRule


# ---------------------------------------------------------------- tiny EBML writer
def vint_size(n: int) -> bytes:
    for length in range(1, 9):
        if n < (1 << (7 * length)) - 1:
            return ((1 << (7 * length)) | n).to_bytes(length, "big")
    raise ValueError(n)


def el(eid: int, payload: bytes, unknown_size: bool = False) -> bytes:
    head = eid.to_bytes((eid.bit_length() + 7) // 8, "big")
    return head + (b"\x01\xff\xff\xff\xff\xff\xff\xff" if unknown_size else vint_size(len(payload))) + payload


def u(eid: int, n: int) -> bytes:
    return el(eid, n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big"))


def s(eid: int, text: str) -> bytes:
    return el(eid, text.encode("utf-8"))


def simple(name: str, value: str) -> bytes:
    return el(0x67C8, s(0x45A3, name) + s(0x4487, value))


def tag(target: int, *simples: bytes, track_uid: int = 0) -> bytes:
    targets = u(0x68CA, target) + (u(0x63C5, track_uid) if track_uid else b"")
    return el(0x7373, el(0x63C0, targets) + b"".join(simples))


def info(title: str = "", seconds: float | None = None, date_ns: int | None = None) -> bytes:
    body = u(0x2AD7B1, 1_000_000)                                  # timestamps in ms
    if seconds is not None:
        body += el(0x4489, struct.pack(">d", seconds * 1000))
    if title:
        body += s(0x7BA9, title)
    if date_ns is not None:
        body += el(0x4461, date_ns.to_bytes(8, "big", signed=True))
    return el(0x1549A966, body)


def tracks(w: int, h: int) -> bytes:
    video = el(0xAE, u(0x83, 1) + el(0xE0, u(0xB0, w) + u(0xBA, h)))
    audio = el(0xAE, u(0x83, 2))
    return el(0x1654AE6B, audio + video)


HEADER = el(0x1A45DFA3, s(0x4282, "matroska"))
CLUSTER = el(0x1F43B675, b"\x00" * 4000)


def mkv(*children: bytes, tail: bytes = CLUSTER) -> bytes:
    return HEADER + el(0x18538067, b"".join(children) + tail)


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------- tiny RIFF writer
def chunk(fourcc: bytes, data: bytes) -> bytes:
    return fourcc + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) & 1 else b"")


def lst(kind: bytes, *chunks: bytes) -> bytes:
    return chunk(b"LIST", kind + b"".join(chunks))


def avi(*lists: bytes) -> bytes:
    body = b"AVI " + b"".join(lists)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def avih(us_per_frame: int, frames: int, w: int, h: int) -> bytes:
    return chunk(b"avih", struct.pack("<10I", us_per_frame, 0, 0, 0, frames, 0, 1, 0, w, h) + b"\x00" * 16)


def text(fourcc: bytes, value: str) -> bytes:
    return chunk(fourcc, value.encode("utf-8") + b"\x00")


def proposed(path: Path, template: str) -> str:
    (row,) = RenameEngine([TemplateRule(template=template)]).preview([path])
    return row.proposed


# ---------------------------------------------------------------- tests
def test_mkv_info_tracks_and_tags(tmp_path):
    data = mkv(info("Some Movie", seconds=5025.4), tracks(1920, 800),
               el(0x1254C367, tag(50, simple("ARTIST", "Jane Doe"), simple("DATE_RELEASED", "2019-05-01"),
                                  simple("GENRE", "Drama"))
                  + tag(50, simple("ENCODER", "x"), track_uid=7)))      # per-track tags are ignored
    meta = read_matroska(write(tmp_path, "m.mkv", data))
    assert meta == {"title": "Some Movie", "width": 1920, "height": 800, "artist": "Jane Doe",
                    "genre": "Drama", "date": datetime(2019, 5, 1), "year": 2019,
                    "duration": "1.23.45", "seconds": 5025}


def test_webm_tv_episode_targets_and_date_utc(tmp_path):
    ns = int((datetime(2021, 3, 4) - datetime(2001, 1, 1)).total_seconds()) * 10**9
    data = mkv(info(seconds=61, date_ns=ns), tracks(1280, 720),
               el(0x1254C367, tag(70, simple("TITLE", "Night Shift")) + tag(60, simple("PART_NUMBER", "2"))
                  + tag(50, simple("TITLE", "Pilot"), simple("PART_NUMBER", "5"))))
    p = write(tmp_path, "e.webm", data)
    meta = MetadataStore().get(p, "video")
    assert meta["show"] == "Night Shift" and meta["season"] == 2 and meta["episode"] == 5
    assert meta["title"] == "Pilot" and meta["year"] == 2021 and meta["duration"] == "1.01"
    assert meta["quality"] == "720p" and meta["resolution"] == "1280x720"
    assert proposed(p, "<show> S<season:2>E<episode:2> - <title> [<quality>]") == "Night Shift S02E05 - Pilot [720p].webm"


def test_mkv_tags_after_the_video_are_found_through_the_seekhead(tmp_path):
    tags = el(0x1254C367, tag(50, simple("ARTIST", "Late Writer")))
    first = info("T") + tracks(640, 480)

    def seekhead(pos: int) -> bytes:
        return el(0x114D9B74, el(0x4DBB, el(0x53AB, bytes.fromhex("1254C367")) + el(0x53AC, pos.to_bytes(2, "big"))))

    position = len(seekhead(0)) + len(first) + len(CLUSTER)        # Tags offset inside the Segment
    data = HEADER + el(0x18538067, seekhead(position) + first + CLUSTER + tags)
    assert read_matroska(write(tmp_path, "late.mkv", data))["artist"] == "Late Writer"


def test_avi_header_and_info_chunk(tmp_path):
    data = avi(lst(b"hdrl", avih(40000, 2250, 720, 576)),
               lst(b"INFO", text(b"INAM", "Holiday"), text(b"IART", "Dad"), text(b"ICRD", "2004-07-15"),
                   text(b"IGNR", "Home video")),
               lst(b"movi", chunk(b"00dc", b"\x00" * 3001)))         # odd size: padded
    p = write(tmp_path, "h.avi", data)
    meta = MetadataStore().get(p, "video")
    assert meta["title"] == "Holiday" and meta["artist"] == "Dad" and meta["genre"] == "Home video"
    assert meta["year"] == 2004 and meta["duration"] == "1.30" and meta["quality"] == "576p"
    assert proposed(p, "<year> <artist> - <title>") == "2004 Dad - Holiday.avi"


def test_avi_info_after_movi_and_old_date_style(tmp_path):
    data = avi(lst(b"hdrl", avih(33367, 30, 320, 240)), lst(b"movi", chunk(b"00dc", b"x" * 10)),
               lst(b"INFO", text(b"ICRD", "Wed Jan 02 02:03:55 1990")))
    meta = read_avi(write(tmp_path, "o.avi", data))
    assert meta["year"] == 1990 and meta["seconds"] == 1


def test_wrong_kind_of_file_gives_no_tags(tmp_path):
    for name in ("x.mkv", "x.avi", "x.webm"):
        p = write(tmp_path, name, b"not a video at all" * 10)
        assert read_matroska(p) == {} and read_avi(p) == {}
        assert proposed(p, "<name> <title>") == p.name           # no title: name kept, no crash
    assert read_matroska(write(tmp_path, "empty.mkv", b"")) == {}
    assert read_avi(write(tmp_path, "riffwav.avi", b"RIFF\x04\x00\x00\x00WAVE")) == {}


@pytest.mark.parametrize("kind", ["mkv", "avi"])
def test_cut_off_and_damaged_files_never_raise(kind):
    import io
    if kind == "mkv":
        good = mkv(info("Some Movie", seconds=10), tracks(1920, 1080),
                   el(0x1254C367, tag(50, simple("ARTIST", "A"))),
                   tail=el(0x1F43B675, b"\x00" * 50, unknown_size=True))   # live-stream cluster
        reader = matroska_tags
    else:
        good = avi(lst(b"hdrl", avih(40000, 25, 640, 360)), lst(b"INFO", text(b"INAM", "Clip")))
        reader = avi_tags

    def read(data: bytes) -> dict:
        return reader(io.BytesIO(data), len(data))

    assert read(good)
    for cut in range(len(good)):                               # every truncation
        assert isinstance(read(good[:cut]), dict)
    for i in range(len(good)):                                 # every byte flipped, sizes included
        bad = bytearray(good)
        bad[i] ^= 0xFF
        assert isinstance(read(bytes(bad)), dict)
