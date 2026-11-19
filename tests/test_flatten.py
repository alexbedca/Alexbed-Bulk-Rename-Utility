"""Flatten a folder: files move up, emptied subfolders go, History can undo and redo it."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from alexed_bru.core import flatten as fl
from alexed_bru.core.history import History
from test_ui import app, pump, win  # noqa: F401  (shared window fixtures)


def tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def state(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()}


def dirs(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())


MUSIC = {"top.txt": "t", "Album A/01 Intro.mp3": "a1", "Album A/cover.jpg": "ac",
         "Album A/CD1/01 Intro.mp3": "cd1", "Album B/01 Intro.mp3": "b1", "Album B/cover.jpg": "bc"}


def test_flatten_numbers_clashes_and_removes_emptied_folders(tmp_path):
    root = tree(tmp_path / "Music", MUSIC)
    (root / "Empty sub").mkdir()
    history = History(tmp_path / "h.json")
    plan = fl.plan_flatten(root)
    assert len(plan.moves) == 5 and plan.renamed == 3
    assert fl.apply_flatten(plan, history).ok
    assert state(root) == {"top.txt": "t", "01 Intro.mp3": "a1", "cover.jpg": "ac", "01 Intro (1).mp3": "cd1",
                           "01 Intro (2).mp3": "b1", "cover (1).jpg": "bc"}
    assert dirs(root) == []                          # Album A, CD1, Album B and the empty one are gone

    batch = history.batches[-1]
    assert history.rollback(batch).ok                # undo: folders recreated, files back
    assert state(root) == MUSIC
    assert dirs(root) == ["Album A", "Album A/CD1", "Album B"]
    assert history.reapply(batch).ok                 # redo
    assert dirs(root) == [] and len(state(root)) == 6


def test_folder_name_mode(tmp_path):
    root = tree(tmp_path / "Music", MUSIC)
    plan = fl.plan_flatten(root, clash=fl.CLASH_FOLDER)
    names = sorted(m.dst.name for m in plan.moves)
    assert names == ["01 Intro.mp3", "Album A - CD1 - 01 Intro.mp3", "Album B - 01 Intro.mp3",
                     "Album B - cover.jpg", "cover.jpg"]


def test_depth_one_moves_only_the_first_level(tmp_path):
    root = tree(tmp_path / "Music", MUSIC)
    plan = fl.plan_flatten(root, depth=1)
    assert fl.apply_flatten(plan).ok
    assert "Album A/CD1/01 Intro.mp3" in state(root)            # deeper level untouched
    assert dirs(root) == ["Album A", "Album A/CD1"]               # Album A kept: it still holds CD1


def test_skips_duplicates_folder_clutter_and_temp_files(tmp_path):
    root = tree(tmp_path / "Pics", {"A/x.jpg": "x", "A/Thumbs.db": "db", "_Duplicates/y.jpg": "y",
                                     "B/.~abru-1234.tmp": "tmp"})
    plan = fl.plan_flatten(root)
    assert [m.src.name for m in plan.moves] == ["x.jpg"]
    assert {p.name for p, _ in plan.skipped} == {"Thumbs.db", "_Duplicates", ".~abru-1234.tmp"}
    assert fl.apply_flatten(plan).ok
    assert sorted(fl.left_folders(plan)) == [root / "A", root / "B"]   # still hold skipped files
    assert (root / "_Duplicates" / "y.jpg").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_folder_links_are_not_followed(tmp_path):
    outside = tree(tmp_path / "outside", {"secret.txt": "s"})
    root = tree(tmp_path / "Root", {"A/a.txt": "a"})
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)], check=True,
                   capture_output=True)
    plan = fl.plan_flatten(root)
    assert [m.src.name for m in plan.moves] == ["a.txt"]
    assert any("link" in reason.lower() for _, reason in plan.skipped)
    assert fl.apply_flatten(plan).ok
    assert (outside / "secret.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locks")
def test_locked_file_rolls_back_everything(tmp_path):
    root = tree(tmp_path / "Music", MUSIC)
    before, history = state(root), History(tmp_path / "h.json")
    plan = fl.plan_flatten(root)
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sys; f=open(sys.argv[1],'rb'); print('ok', flush=True); sys.stdin.read()",
                               str(root / "Album B" / "cover.jpg")], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        result = fl.apply_flatten(plan, history)
    finally:
        holder.stdin.close()
        holder.wait(10)
    assert not result.ok and result.rolled_back
    assert state(root) == before and dirs(root) == ["Album A", "Album A/CD1", "Album B"]
    assert history.batches == []


def test_nothing_to_do(tmp_path):
    root = tree(tmp_path / "Flat", {"a.txt": "a"})
    plan = fl.plan_flatten(root)
    assert plan.moves == [] and fl.apply_flatten(plan).ok
    assert os.listdir(root) == ["a.txt"]


def test_flatten_window_end_to_end(app, win, tmp_path, monkeypatch):
    from alexed_bru.ui import flatten_dialog as fd
    root = tree(tmp_path / "Music", MUSIC)
    monkeypatch.setattr(fd.QMessageBox, "question", staticmethod(lambda *a, **k: fd.QMessageBox.Yes))
    monkeypatch.setattr(fd.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    dlg = fd.FlattenDialog(win, root)
    dlg.show()
    assert pump(app, lambda: dlg.plan is not None)
    assert dlg.go.isEnabled() and "Moves 5 file(s) from 3 subfolder(s)" in dlg.summary.text()
    assert dlg.tree.topLevelItemCount() == 5
    dlg.clash.setCurrentIndex(1)                                   # options re-plan
    assert pump(app, lambda: dlg.plan is not None and dlg.plan.moves[-1].dst.name.startswith("Album"))
    dlg.go.click()
    assert pump(app, lambda: not (root / "Album A").exists())
    assert pump(app, lambda: len(win.model.items) == 6)            # loaded into the rename list
    assert win.history.batches[-1].label.startswith("Flattened Music")
    assert win.rollback_batch(win.history.batches[-1], redo=False)
    assert state(root) == MUSIC


def test_only_empty_subfolders_are_removed(tmp_path):
    root = tree(tmp_path / "R", {"a.txt": "a", "keep/Thumbs.db": "x"})
    (root / "empty" / "deeper").mkdir(parents=True)
    plan = fl.plan_flatten(root)
    assert plan.moves == [] and fl.empty_folders(plan) == [root / "empty", root / "empty" / "deeper"]
    assert fl.apply_flatten(plan).ok
    assert dirs(root) == ["keep"]                     # only the folder holding a skipped file stays
