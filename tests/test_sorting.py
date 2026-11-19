"""Sort by tags and manual order: counters follow the list order."""
from datetime import datetime
from pathlib import Path

from alexed_bru.core import sorting
from alexed_bru.core.models import FileItem
from alexed_bru.skills.rules import CounterRule
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)


def items(*names):
    return [FileItem(Path("C:/x") / n) for n in names]


def test_order_by_date_taken_with_untagged_last():
    its = items("c.jpg", "a.jpg", "b.jpg", "notag.jpg")
    taken = {"c.jpg": datetime(2024, 1, 3), "a.jpg": datetime(2023, 5, 1), "b.jpg": datetime(2024, 1, 1)}

    def meta(item, ns):
        if ns == "exif":
            return {"date": taken.get(item.name)}
        return {"modified": None}

    assert sorting.order(its, "taken", meta) == [1, 2, 0, 3]
    assert sorting.order(its, "taken", meta, reverse=True) == [0, 2, 1, 3]   # untagged still last


def test_order_by_track_then_disc_and_size():
    its = items("x.mp3", "y.mp3", "z.mp3")
    tags = {"x.mp3": {"disc": 2, "track": 1}, "y.mp3": {"disc": 1, "track": 9}, "z.mp3": {"track": 3}}
    assert sorting.order(its, "track", lambda it, ns: tags[it.name]) == [2, 1, 0]   # no disc counts as 0
    sizes = {"x.mp3": 30, "y.mp3": 10, "z.mp3": 20}
    assert sorting.order(its, "size", lambda it, ns: {"size": sizes[it.name]}) == [1, 2, 0]


def test_natural_name_and_folder_order():
    its = items("Track 10.mp3", "Track 2.mp3", "track 1.mp3")
    assert sorting.order(its, "name", lambda *_: None) == [2, 1, 0]


def test_move_rows_and_drag(app, win, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    for n in ("a.txt", "b.txt", "c.txt", "d.txt"):
        (lib / n).write_text(n)
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == 4)
    win.set_rules([CounterRule(placement="prefix", separator=" ")])
    assert pump(app, lambda: idle(win) and win.model.proposals[0].new_name == "01 a.txt")

    model = win.model
    names = lambda: [i.name for i in model.items]  # noqa: E731
    assert model.move_rows([3], "top") == [0] and names() == ["d.txt", "a.txt", "b.txt", "c.txt"]
    assert model.move_rows([0], "down") == [1] and names() == ["a.txt", "d.txt", "b.txt", "c.txt"]
    assert model.move_rows([0, 1], "bottom") == [2, 3] and names() == ["b.txt", "c.txt", "a.txt", "d.txt"]

    data = model.mimeData([model.index(3, 0)])                     # drag d.txt onto row 0
    model.dropMimeData(data, None, 0, 0, model.index(-1, -1))
    assert names() == ["d.txt", "b.txt", "c.txt", "a.txt"]
    assert pump(app, lambda: idle(win) and win.model.proposals[0].new_name == "01 d.txt")  # counter follows

    win.search.setText("a")                                        # filtered: no dragging
    assert not win.table.dragEnabled()
    win.search.setText("")
    assert win.table.dragEnabled()


def test_sort_menu_by_size(app, win, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    for n, size in (("big.txt", 300), ("small.txt", 10), ("mid.txt", 100)):
        (lib / n).write_bytes(b"x" * size)
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == 3)
    win.sort_by("size")
    assert pump(app, lambda: [i.name for i in win.model.items] == ["small.txt", "mid.txt", "big.txt"])
    win.sort_reverse.setChecked(True)
    win.sort_by("size")
    assert pump(app, lambda: [i.name for i in win.model.items] == ["big.txt", "mid.txt", "small.txt"])


def test_files_dropped_from_explorer_onto_the_table_are_still_added(app, win, tmp_path):
    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    (tmp_path / "dropped.txt").write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "dropped.txt"))])
    viewport, pos = win.table.viewport(), QPoint(20, 20)
    enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(viewport, enter)
    drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(viewport, drop)
    assert pump(app, lambda: [i.name for i in win.model.items] == ["dropped.txt"])
