"""Folder renaming mode: folders inside renamed folders, undo/redo, failures, the window."""
import os
import sys
from pathlib import Path

import pytest

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.transaction import RenameOp, _layers, execute, where_now
from alexed_bru.skills.rules import CaseRule, PrefixSuffixRule, ReplaceRule
from alexed_bru.ui.main_window import scan_folders
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() + ("/" if p.is_dir() else "") for p in root.rglob("*"))


def make(root: Path) -> Path:
    for rel in ("artist a/album one/01.mp3", "artist a/album two/01.mp3", "artist b/live/01.mp3", "artist b/x.txt"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel)
    (root / "artist b" / "empty").mkdir()
    return root


def folders(root: Path) -> list[Path]:
    return scan_folders([root], contents=True, recursive=True, cancelled=lambda: False)


def test_scan_lists_subfolders_or_the_dropped_folders(tmp_path):
    root = make(tmp_path / "Music")
    (root / "$RECYCLE.BIN").mkdir()
    (root / ".~abru-x.tmp").mkdir()
    rel = lambda ps: [p.relative_to(root).as_posix() for p in ps]  # noqa: E731
    assert rel(folders(root)) == ["artist a", "artist a/album one", "artist a/album two",
                                  "artist b", "artist b/empty", "artist b/live"]
    assert rel(scan_folders([root], True, False, lambda: False)) == ["artist a", "artist b"]
    dropped = scan_folders([root / "artist a", root / "artist b" / "x.txt"], False, True, lambda: False)
    assert rel(dropped) == ["artist a"]                               # files are left out
    assert scan_folders([Path(root.anchor)], False, True, lambda: False) == []   # never a drive root


def test_parent_and_children_renamed_together_then_undo_redo(tmp_path):
    root = make(tmp_path / "Music")
    before = tree(root)
    history = History(tmp_path / "h.json")
    engine = RenameEngine([CaseRule(mode="title")], history=history)
    paths = folders(root)
    rows = engine.preview(paths)
    assert [r.proposed for r in rows] == ["Artist A", "Album One", "Album Two", "Artist B", "Empty", "Live"]
    result = engine.apply(paths)
    assert result.ok and result.nested
    assert tree(root) == ["Artist A/", "Artist A/Album One/", "Artist A/Album One/01.mp3", "Artist A/Album Two/",
                          "Artist A/Album Two/01.mp3", "Artist B/", "Artist B/Empty/", "Artist B/Live/",
                          "Artist B/Live/01.mp3", "Artist B/x.txt"]
    batch = History.load(tmp_path / "h.json").batches[-1]               # survives a restart
    assert history.rollback(batch).ok and tree(root) == before
    assert history.reapply(batch).ok and "Artist A/Album One/01.mp3" in tree(root)
    assert history.rollback(batch).ok and tree(root) == before


def test_folder_names_keep_their_dots(tmp_path):
    (tmp_path / "Vol. 2.0 live").mkdir()
    (row,) = RenameEngine([CaseRule(mode="upper")]).preview([tmp_path / "Vol. 2.0 live"])
    assert row.proposed == "VOL. 2.0 LIVE"                              # no "extension" for folders


@pytest.mark.skipif(sys.platform != "win32", reason="Windows refuses to rename a folder with an open file")
def test_open_file_in_a_parent_rolls_back_the_children_too(tmp_path):
    root = make(tmp_path / "Music")
    (root / "artist a" / "cover.jpg").write_text("c")
    before = tree(root)
    history = History(tmp_path / "h.json")
    paths = folders(root)
    renamed_first = []
    import alexed_bru.core.transaction as tx
    real = tx._execute_flat

    def spy(ops, *a, **k):
        result = real(ops, *a, **k)
        renamed_first.append((len(ops), result.ok))
        return result

    tx._execute_flat = spy
    try:
        # the subfolders (first layer) can be renamed; "artist a" itself can't while cover.jpg is open
        with open(root / "artist a" / "cover.jpg", "rb"):
            result = RenameEngine([PrefixSuffixRule(prefix="X ")], history=history).apply(paths)
    finally:
        tx._execute_flat = real
    assert renamed_first[0] == (4, True)                                # children were renamed...
    assert not result.ok and result.rolled_back and not result.stuck   # ...and put back
    assert tree(root) == before and history.batches == []


def test_case_only_folder_rename(tmp_path):
    (tmp_path / "album").mkdir()
    (tmp_path / "album" / "a.txt").write_text("a")
    result = RenameEngine([CaseRule(mode="title")]).apply([tmp_path / "album"])
    assert result.ok and os.listdir(tmp_path) == ["Album"]


def test_layers_order_children_first_and_parents_first_when_undoing(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    forward = [RenameOp(a, b), RenameOp(a / "x", a / "y")]
    assert [[op.src.name for op in layer] for layer in _layers(forward)] == [["x"], ["a"]]
    undo = [op.inverse() for op in forward]
    assert [[op.src.name for op in layer] for layer in _layers(undo)] == [["b"], ["y"]]
    files = [RenameOp(a / "1.txt", a / "2.txt"), RenameOp(b / "c" / "3.txt", b / "c" / "4.txt")]
    assert len(_layers(files)) == 1                                     # plain files: one fast pass
    final = where_now([a, a / "x"], [RenameOp(a / "x", a / "y"), RenameOp(a, b)])
    assert sorted(p.relative_to(tmp_path).as_posix() for p in final.values()) == ["b", "b/y"]


def test_failing_undo_layer_changes_nothing(tmp_path):
    root = make(tmp_path / "Music")
    history = History(tmp_path / "h.json")
    paths = folders(root)
    assert RenameEngine([ReplaceRule(find="artist", replace="Band")], history=history).apply(paths).ok
    after = tree(root)
    (root / "artist a").mkdir()                     # undo of "Band a" -> "artist a" now blocked
    result = history.rollback(history.batches[-1])
    assert not result.ok and tree(root) == sorted(after + ["artist a/"])


def test_window_folder_mode_end_to_end(app, win, tmp_path, monkeypatch):
    root = make(tmp_path / "Music")
    before = tree(root)
    win.set_folder_mode(True)
    assert win.mode_folders.isChecked() and not win.dup_btn.isEnabled()
    win.add_paths([root], contents=True)
    assert pump(app, lambda: len(win.model.items) == 6)
    assert all(i.is_dir for i in win.model.items)
    win.set_rules([ReplaceRule(find="artist", replace="Band")])
    assert pump(app, lambda: idle(win) and win.apply_btn.text() == "Rename 2 folders")
    win.apply()
    assert pump(app, lambda: (root / "Band a").exists())
    assert pump(app, lambda: "2 renamed" in win.counts.text())     # only the 2 renamed, not those inside
    # rows inside a renamed folder now point at its new name
    listed = sorted(str(i.path.relative_to(root)).replace("\\", "/") for i in win.model.items)
    assert listed == ["Band a", "Band a/album one", "Band a/album two", "Band b", "Band b/empty", "Band b/live"]
    assert all(i.path.exists() for i in win.model.items)
    assert win.rollback_batch(win.history.batches[-1], redo=False)
    assert tree(root) == before and all(i.path.exists() for i in win.model.items)
    # the folder holding this app's data folder can't be renamed while the app runs
    import alexed_bru.ui.main_window as mw
    warned = []
    monkeypatch.setattr(mw.QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    win.clear_files()
    win.add_paths([tmp_path])                       # holds the test's data folder
    assert pump(app, lambda: len(win.model.items) == 1)
    win.set_rules([PrefixSuffixRule(prefix="X ")])
    assert pump(app, lambda: idle(win) and win.apply_btn.isEnabled())
    win.apply()
    assert warned and "holds this app" in warned[0] and tmp_path.exists()
    win.set_folder_mode(False)                      # back to files: list cleared, Duplicates back
    assert win.model.items == [] and win.dup_btn.isEnabled()


def test_warns_when_a_longer_folder_name_pushes_paths_past_260(tmp_path):
    from alexed_bru.core.transaction import too_long_after
    base = tmp_path / "a"
    deep = base / ("d" * 60)
    deep.mkdir(parents=True)
    room = 250 - len(str(deep)) - 1                  # a file whose path is 250 characters long
    (deep / ("f" * room)).write_text("x")
    grow = RenameOp(base, tmp_path / "a-much-longer-name")
    assert too_long_after([grow]) == [base]
    assert too_long_after([RenameOp(base, tmp_path / "b")]) == []          # same length: fine
    assert too_long_after([grow], budget=0) in ([], [base])                # capped look-ahead
