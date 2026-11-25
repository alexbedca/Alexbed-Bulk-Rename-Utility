"""Loading big folders without freezing: fast row records, rows added in chunks."""
from pathlib import Path

from alexed_bru.core.models import FileItem
from alexed_bru.ui.preview_model import keyed_items
from test_ui import app, pump, win  # noqa: F401  (shared window fixtures)


def test_fast_path_split_matches_pathlib():
    for raw in (r"C:\Music\Album\01 song.mp3", r"C:\top.txt", r"\\server\share\dir\a.b.c",
                r"D:\x\.gitignore", r"D:\x\no extension", r"D:\x\trailing dot."):
        p = Path(raw)
        item = FileItem(p)
        assert item.name == p.name and item.folder_key == str(p.parent) and item.folder == p.parent
    folder = FileItem(Path(r"D:\a\Album 2.0"), is_dir=True)
    assert (folder.stem, folder.ext) == ("Album 2.0", "")


def test_copy_is_independent_and_keeps_everything():
    item = FileItem(Path(r"C:\a\b.txt"), include=False, manual="x.txt", is_dir=False)
    twin = item.copy()
    assert (twin.path, twin.name, twin.stem, twin.ext, twin.folder_key, twin.include, twin.manual) == \
        (item.path, item.name, item.stem, item.ext, item.folder_key, item.include, item.manual)
    twin.manual = None
    assert item.manual == "x.txt"


def test_rows_are_added_in_chunks_and_late_or_cleared_ones_are_dropped(app, win, tmp_path):
    win.ROW_CHUNK = 4                                  # small chunks: same code path, quick test
    paths = [tmp_path / f"f{i}.txt" for i in range(10)]   # not created: rows only
    win._on_scanned(keyed_items(paths))
    assert len(win.model.items) == 4                   # first chunk at once, the rest on later turns
    assert pump(app, lambda: len(win.model.items) == 10)
    assert win._pending_rows == [] and win._added == 10
    win._on_scanned(keyed_items(paths[:2] + [tmp_path / f"new{i}.txt" for i in range(9)]))
    win.clear_files()                                  # Clear while chunks wait
    for _ in range(10):
        app.processEvents()                            # a waiting chunk would run now
    assert win.model.items == []
    old_list = win._list_id
    win.set_folder_mode(True)                          # a scan that finishes after a mode switch
    win._on_scanned(keyed_items([tmp_path / "late.txt"]), old_list)
    assert win.model.items == []
