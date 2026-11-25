"""Real media files (generated with ffmpeg when available) and the general-purpose rules."""
import shutil
from concurrent.futures import ThreadPoolExecutor
import subprocess
from pathlib import Path

import pytest

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.models import Status
from alexed_bru.skills.metadata import MetadataStore
from alexed_bru.skills.rules import (CounterRule, PrefixSuffixRule, ReplaceRule, TemplateRule)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed (only needed to make fixtures)")


def job(*args, **meta):
    return args, meta


def ffmpeg(out: Path, inputs: list[str], *extra: str, **meta: str) -> Path:
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs, *extra]
    for k, v in meta.items():
        args += ["-metadata", f"{k}={v}"]
    subprocess.run([*args, str(out)], check=True, timeout=60)
    return out


VIDEO = ["-f", "lavfi", "-i", "testsrc=duration=1:size=1920x1080:rate=1"]  # 1 frame: tags only
SMALL_VIDEO = ["-f", "lavfi", "-i", "testsrc=duration=1:size=1280x720:rate=1"]
AUDIO = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("media")
    jobs = {
        "mp4": job(d / "VID_20240101.mp4", VIDEO, "-pix_fmt", "yuv420p",
                      title="Pilot", artist="Studio X", date="2019", show="Night Shift",
                      season_number="2", episode_sort="5", genre="Drama"),
        "mov": job(d / "clip.mov", SMALL_VIDEO, "-pix_fmt", "yuv420p", title="Behind the Scenes"),
        "iphone": job(d / "IMG_4821.MOV", SMALL_VIDEO, "-pix_fmt", "yuv420p", "-movflags",
                         "use_metadata_tags", **{"com.apple.quicktime.creationdate": "2023-06-01T14:22:09+0100",
                                                 "com.apple.quicktime.make": "Apple",
                                                 "com.apple.quicktime.model": "iPhone 14 Pro"}),
        "untagged_mp4": job(d / "raw.mp4", SMALL_VIDEO, "-pix_fmt", "yuv420p"),
        "flac": job(d / "04 - track.flac", AUDIO, ARTIST="Nina Simone", TITLE="Feeling Good",
                       ALBUM="I Put a Spell on You", TRACKNUMBER="4/12", DATE="1965", GENRE="Jazz"),
        "m4a": job(d / "song.m4a", AUDIO, "-c:a", "aac", artist="Miles Davis", title="So What",
                      album="Kind of Blue", track="1", date="1959"),
        "mkv": job(d / "movie.mkv", SMALL_VIDEO, title="Some Movie", artist="Jane Doe", date="2019-05-01"),
        "avi": job(d / "clip.avi", SMALL_VIDEO, "-c:v", "mpeg4", title="Home Video", artist="Dad", date="2004"),
        "wmv": job(d / "show.wmv", SMALL_VIDEO, "-c:v", "wmv2", title="Pilot", artist="Night Shift", date="2021"),
        "flv": job(d / "old.flv", SMALL_VIDEO, "-c:v", "flv1", title="Old Clip", artist="Mum", date="2008"),
        "ogg": job(d / "voice.ogg", AUDIO, "-c:a", "libvorbis", ARTIST="Narrator", TITLE="Chapter 1"),
    }
    # ffmpeg runs in parallel: the fast suite has a 15-second budget
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {k: pool.submit(lambda a=args: ffmpeg(*a[0], **a[1])) for k, args in jobs.items()}
        return {k: f.result() for k, f in futures.items()}


def preview(path, template):
    (row,) = RenameEngine([TemplateRule(template=template)]).preview([path])
    return row


@needs_ffmpeg
def test_mp4_video_tags_and_resolution(media):
    data = MetadataStore().get(media["mp4"], "video")
    assert data["title"] == "Pilot" and data["show"] == "Night Shift"
    assert data["season"] == 2 and data["episode"] == 5 and data["year"] == 2019
    assert data["resolution"] == "1920x1080" and data["quality"] == "1080p"
    assert data["duration"] == "0.01"
    row = preview(media["mp4"], "<show> S<season:2>E<episode:2> - <title> [<quality>]")
    assert row.proposed == "Night Shift S02E05 - Pilot [1080p].mp4" and row.status == Status.PENDING


@needs_ffmpeg
def test_mov_and_untagged_video(media):
    assert preview(media["mov"], "<title> <resolution>").proposed == "Behind the Scenes 1280x720.mov"
    # No title tag: keeps the original name, flags a warning, still reads the resolution
    row = preview(media["untagged_mp4"], "<title>")
    assert row.proposed == "raw.mp4" and row.status == Status.UNCHANGED
    assert preview(media["untagged_mp4"], "<name> [<quality>]").proposed == "raw [720p].mp4"


@needs_ffmpeg
def test_flac_vorbis_comments(media):
    row = preview(media["flac"], "<track:2>. <artist> - <title> (<year>)")
    assert row.proposed == "04. Nina Simone - Feeling Good (1965).flac"
    data = MetadataStore().get(media["flac"], "audio")
    assert data["album"] == "I Put a Spell on You" and data["genre"] == "Jazz"
    assert data["samplerate"] == 44100


@needs_ffmpeg
def test_m4a_and_ogg(media):
    assert preview(media["m4a"], "<artist> - <album> - <track:2> <title>").proposed \
        == "Miles Davis - Kind of Blue - 01 So What.m4a"
    assert preview(media["ogg"], "<artist> - <title>").proposed == "Narrator - Chapter 1.ogg"


@needs_ffmpeg
def test_mkv_and_avi_made_by_ffmpeg(media):
    row = preview(media["mkv"], "<artist> - <title> (<year>) [<quality>] <duration>")
    assert row.proposed == "Jane Doe - Some Movie (2019) [720p] 0.01.mkv"
    assert preview(media["avi"], "<year> <artist> - <title> <resolution>").proposed \
        == "2004 Dad - Home Video 1280x720.avi"


@needs_ffmpeg
def test_wmv_and_flv_made_by_ffmpeg(media):
    assert preview(media["wmv"], "<artist> - <title> (<year>) [<quality>]").proposed \
        == "Night Shift - Pilot (2021) [720p].wmv"
    assert preview(media["flv"], "<year> <artist> - <title> <resolution>").proposed \
        == "2008 Mum - Old Clip 1280x720.flv"


# ---------------------------------------------------------------------------
# General-purpose rules on any kind of file
# ---------------------------------------------------------------------------
MIXED = ["Holiday 07.jpg", "Report v3.pdf", "Track 12 - intro.mp3", "notes.txt", "Clip 2.mp4"]


def mixed(tmp_path):
    out = []
    for n in MIXED:
        p = tmp_path / n
        p.write_bytes(b"x")
        out.append(p)
    return out


def proposed(paths, *rules):
    return [r.proposed for r in RenameEngine(list(rules)).preview(paths)]


def test_prefix_and_suffix_any_file(tmp_path):
    paths = mixed(tmp_path)
    assert proposed(paths, PrefixSuffixRule(prefix="2024 - ", suffix=" (final)")) == [
        "2024 - Holiday 07 (final).jpg", "2024 - Report v3 (final).pdf",
        "2024 - Track 12 - intro (final).mp3", "2024 - notes (final).txt", "2024 - Clip 2 (final).mp4"]
    # "Don't add twice" makes the rule safe to re-run
    assert proposed([tmp_path / "Holiday 07.jpg"], PrefixSuffixRule(prefix="Holi")) == ["Holiday 07.jpg"]
    # Tags work in prefixes too
    assert proposed([tmp_path / "notes.txt"], PrefixSuffixRule(prefix="<num:3>_")) == ["001_notes.txt"]


def test_find_and_replace_all_vs_first(tmp_path):
    p = tmp_path / "a_b_c_d.txt"
    p.write_bytes(b"")
    assert proposed([p], ReplaceRule(find="_", replace=" ")) == ["a b c d.txt"]
    assert proposed([p], ReplaceRule(find="_", replace=" ", occurrence="first")) == ["a b_c_d.txt"]
    assert proposed([p], ReplaceRule(find="_", replace="")) == ["abcd.txt"]  # delete


def test_renumber_existing_numbers(tmp_path):
    paths = mixed(tmp_path)
    assert proposed(paths, CounterRule(placement="renumber_first", start=1, padding=2)) == [
        "Holiday 01.jpg", "Report v02.pdf", "Track 03 - intro.mp3", "notes - 04.txt", "Clip 05.mp4"]
    assert proposed(paths, CounterRule(placement="renumber_first", padding=2, no_number="start"))[3] \
        == "04 - notes.txt"
    assert proposed(paths, CounterRule(placement="renumber_first", padding=2, no_number="skip"))[3] \
        == "notes.txt"


def test_renumber_preset_on_copies(tmp_path):
    """'ALMP.png', 'ALMP preview.png', 'ALMP preview 2.png': natural order, same style."""
    from alexed_bru.core import presets
    from alexed_bru.ui.main_window import scan
    for n in ("ALMP  preview 2.png", "ALMP  preview.png", "ALMP.png"):
        (tmp_path / n).write_bytes(b"")
    paths = scan([tmp_path], recursive=False, cancelled=lambda: False)
    assert [p.name for p in paths] == ["ALMP.png", "ALMP  preview.png", "ALMP  preview 2.png"]
    rules = presets.samples()["Renumber existing numbers (01, 02, ...)"]
    assert proposed(paths, *rules) == ["ALMP 01.png", "ALMP  preview 02.png", "ALMP  preview 03.png"]


def test_renumber_last_and_counter_suffix(tmp_path):
    p = tmp_path / "S01 E09 show.mkv"
    p.write_bytes(b"")
    assert proposed([p], CounterRule(placement="renumber_last", start=1, padding=2)) == ["S01 E01 show.mkv"]
    assert proposed([p], CounterRule(placement="suffix", separator=" #", padding=3)) == ["S01 E09 show #001.mkv"]


@needs_ffmpeg
def test_iphone_style_mdta_keys(media):
    data = MetadataStore().get(media["iphone"], "video")
    assert data["make"] == "Apple" and data["model"] == "iPhone 14 Pro"
    assert data["date"].strftime("%Y-%m-%d %H:%M:%S") == "2023-06-01 14:22:09"
    row = preview(media["iphone"], "<date:%Y-%m-%d_%H%M%S> <video:model>")
    assert row.proposed == "2023-06-01_142209 iPhone 14 Pro.MOV"
