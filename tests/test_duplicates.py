"""Find duplicates: content matching, keep suggestion, and the undoable move."""
import os
import time
from pathlib import Path

import pytest

from alexed_bru.core import duplicates as dup
from alexed_bru.core.history import History


def write(path: Path, data: bytes, age: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


def test_finds_identical_content_regardless_of_name(tmp_path):
    a = write(tmp_path / "song.mp3", b"music" * 100)
    b = write(tmp_path / "sub" / "other name.mp3", b"music" * 100)
    write(tmp_path / "different.mp3", b"MUSIC" * 100)        # same size, different bytes
    write(tmp_path / "shorter.mp3", b"music")                # different size
    groups = dup.find_duplicates(tmp_path.rglob("*.mp3"))
    assert len(groups) == 1
    assert sorted(groups[0].paths) == sorted([a, b])
    assert groups[0].wasted == 500


def test_large_files_differing_after_first_block_are_not_duplicates(tmp_path):
    head = b"x" * dup.HEAD_BYTES
    write(tmp_path / "a.bin", head + b"tail-one")
    write(tmp_path / "b.bin", head + b"tail-two")
    c = write(tmp_path / "c.bin", head + b"tail-one")
    groups = dup.find_duplicates(tmp_path.iterdir())
    assert [sorted(p.name for p in g.paths) for g in groups] == [["a.bin", "c.bin"]]
    assert c in groups[0].paths


def test_empty_files_and_repeated_paths_are_ignored(tmp_path):
    e1 = write(tmp_path / "e1.txt", b"")
    write(tmp_path / "e2.txt", b"")
    one = write(tmp_path / "one.txt", b"same")
    assert dup.find_duplicates([e1, tmp_path / "e2.txt", one, one]) == []


def test_cancel_returns_none(tmp_path):
    write(tmp_path / "a.txt", b"same")
    write(tmp_path / "b.txt", b"same")
    assert dup.find_duplicates(tmp_path.iterdir(), cancelled=lambda: True) is None


@pytest.mark.parametrize("name,is_copy", [
    ("photo (1).jpg", True), ("photo - Copy.jpg", True), ("photo - Copy (2).jpg", True),
    ("photo copy.jpg", True), ("photo_copy.jpg", True), ("Copy of photo.jpg", True),
    ("photo.jpg", False), ("Live (1999).mp3", False), ("Photocopy.pdf", False),
])
def test_copy_names(name, is_copy):
    assert dup.looks_like_copy(name) is is_copy


def test_keep_suggestion_prefers_original_name_then_oldest(tmp_path):
    copy = write(tmp_path / "photo (1).jpg", b"img", age=9999)   # oldest, but named like a copy
    newer = write(tmp_path / "photo.jpg", b"img", age=10)
    older = write(tmp_path / "holiday.jpg", b"img", age=500)
    paths = [copy, newer, older]
    assert paths[dup.suggest_keep(paths)] == older
    assert paths[dup.suggest_keep([copy, newer])] == newer


def test_move_to_folder_is_undoable_and_never_overwrites(tmp_path):
    keep = write(tmp_path / "a.txt", b"same")
    extra = write(tmp_path / "b.txt", b"same")
    sub_extra = write(tmp_path / "sub" / "a.txt", b"same")
    # an older copy already set aside with the same name must not be overwritten
    write(tmp_path / dup.DUPLICATES_FOLDER / "b.txt", b"old")
    history = History(tmp_path / "data" / "history.json")

    result = dup.move_to_folder([extra, sub_extra], history)
    assert result.ok
    assert keep.exists() and not extra.exists() and not sub_extra.exists()
    assert (tmp_path / dup.DUPLICATES_FOLDER / "b (2).txt").read_bytes() == b"same"
    assert (tmp_path / dup.DUPLICATES_FOLDER / "b.txt").read_bytes() == b"old"
    assert (tmp_path / "sub" / dup.DUPLICATES_FOLDER / "a.txt").exists()
    assert len(history.batches) == 1

    assert history.rollback(history.batches[0]).ok
    assert extra.read_bytes() == b"same" and sub_extra.read_bytes() == b"same"


def test_move_failure_changes_nothing(tmp_path):
    extra = write(tmp_path / "b.txt", b"same")
    missing = tmp_path / "gone.txt"
    result = dup.move_to_folder([extra, missing])
    assert not result.ok
    assert extra.exists()
    assert not (tmp_path / dup.DUPLICATES_FOLDER).exists()  # empty folder cleaned up


@pytest.mark.skipif(os.name != "nt", reason="Windows drive types")
def test_recycle_refuses_network_paths(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(dup, "_shell_recycle", lambda paths: called.append(paths))
    unc = Path(r"\\server\share\a.txt")
    assert dup.can_recycle(unc) is False
    assert dup.recycle([unc]) == [unc]
    assert called == []
