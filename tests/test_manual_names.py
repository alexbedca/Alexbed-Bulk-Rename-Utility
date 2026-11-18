"""Names typed by hand for single files: engine, validation, History and the preview table."""
from pathlib import Path

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.models import Status
from alexed_bru.skills.rules import CounterRule, ReplaceRule
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)


def files(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        (folder / n).write_text(n)
        out.append(folder / n)
    return out


def test_override_replaces_rules_for_that_file_only(tmp_path):
    a, b, c = files(tmp_path, "a.txt", "b.txt", "c.txt")
    engine = RenameEngine([CounterRule()])
    rows = engine.preview([a, b, c], overrides={b: "Special name.txt"})
    assert [r.proposed for r in rows] == ["01 - a.txt", "Special name.txt", "03 - c.txt"]  # numbers don't shift
    assert rows[1].status == Status.PENDING
    # paths match however they are written
    rows = engine.preview([a, b, c], overrides={str(b).upper(): "X.txt"})
    assert rows[1].proposed == "X.txt"


def test_override_goes_through_the_same_checks(tmp_path):
    a, b = files(tmp_path, "a.txt", "b.txt")
    engine = RenameEngine([ReplaceRule(find="a", replace="z")])
    rows = engine.preview([a, b], overrides={b: "z.txt"})       # same as a's new name
    assert rows[0].status == rows[1].status == Status.ERROR
    rows = engine.preview([a, b], overrides={b: "bad?name.txt"})
    assert rows[1].status == Status.ERROR
    rows = engine.preview([a, b], overrides={b: "b.txt"})       # typed its own name
    assert rows[1].status == Status.UNCHANGED


def test_override_applies_and_undoes_through_history(tmp_path):
    a, b = files(tmp_path / "f", "a.txt", "b.txt")
    history = History(tmp_path / "h.json")
    engine = RenameEngine([ReplaceRule(find=".txt", replace="", target="full")], history=history)
    result = engine.apply([a, b], overrides={a: "Hand typed.txt"})
    assert result.ok
    assert sorted(p.name for p in (tmp_path / "f").iterdir()) == ["Hand typed.txt", "b"]
    batch = history.batches[-1]
    assert history.rollback(batch).ok
    assert sorted(p.name for p in (tmp_path / "f").iterdir()) == ["a.txt", "b.txt"]
    assert history.reapply(batch).ok
    assert (tmp_path / "f" / "Hand typed.txt").read_text() == "a.txt"


def test_edit_new_name_in_the_preview_table(app, win, tmp_path):
    from PySide6.QtCore import Qt
    from alexed_bru.ui.preview_model import COL_INFO, COL_NEW
    lib = tmp_path / "lib"
    files(lib, "01 one.txt", "02 two.txt")
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == 2)
    win.set_rules([CounterRule(placement="renumber_first", start=5)])
    assert pump(app, lambda: idle(win) and win.model.proposals[1].new_name == "06 two.txt")

    model = win.model
    cell = model.index(0, COL_NEW)
    assert model.flags(cell) & Qt.ItemIsEditable
    assert model.data(cell, Qt.EditRole) == "05 one.txt"
    assert model.setData(cell, "My pick.txt")
    assert pump(app, lambda: idle(win))
    assert model.proposals[0].new_name == "My pick.txt" and model.proposals[0].manual
    assert model.proposals[1].new_name == "06 two.txt"            # the rules still number the rest
    assert model.data(model.index(0, COL_INFO)) == "Edited by hand"
    assert model.data(cell, Qt.FontRole).italic()
    assert model.data(cell, Qt.DecorationRole) is not None       # pencil mark

    model.reset_manual([0])
    assert pump(app, lambda: idle(win) and model.proposals[0].new_name == "05 one.txt")
    assert not model.proposals[0].manual

    model.setData(cell, "My pick.txt")
    assert pump(app, lambda: idle(win) and model.proposals[0].manual)
    win.apply()
    assert pump(app, lambda: (lib / "My pick.txt").exists() and (lib / "06 two.txt").exists())
    assert pump(app, lambda: model.proposals[0].status == Status.SUCCESS)
    assert model.items[0].manual is None                          # used up by the rename
    assert win.rollback_batch(win.history.batches[-1], redo=False)
    assert (lib / "01 one.txt").exists() and (lib / "02 two.txt").exists()
