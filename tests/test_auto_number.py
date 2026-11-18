"""Auto-number duplicate names: photo.jpg, photo (1).jpg, photo (2).jpg."""
from pathlib import Path

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.models import Status
from alexed_bru.core.validation import NUMBERED_NOTE, numbered
from alexed_bru.skills.rules import RegexRule, ReplaceRule, TemplateRule
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)


def files(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_text(n)
    return [folder / n for n in names]


def all_to_photo():
    """A rule that gives every file the same name."""
    return [TemplateRule(template="photo", fallback_to_original=False)]


def test_numbered():
    assert numbered("photo.jpg", 2) == "photo (2).jpg"
    assert numbered("README", 1) == "README (1)"


def test_off_by_default_duplicates_are_errors(tmp_path):
    paths = files(tmp_path, "a.jpg", "b.jpg", "c.jpg")
    rows = RenameEngine(all_to_photo()).preview(paths)
    assert {r.status for r in rows} == {Status.ERROR}


def test_three_duplicates_are_numbered_applied_and_undone(tmp_path):
    folder = tmp_path / "f"
    paths = files(folder, "a.jpg", "b.jpg", "c.jpg")
    history = History(tmp_path / "h.json")
    engine = RenameEngine(all_to_photo(), history=history, auto_number=True)

    rows = engine.preview(paths)
    assert [r.proposed for r in rows] == ["photo.jpg", "photo (1).jpg", "photo (2).jpg"]
    assert [r.status for r in rows] == [Status.PENDING, Status.WARNING, Status.WARNING]  # amber, not red
    assert rows[1].message == NUMBERED_NOTE

    result = engine.apply(paths)
    assert result.ok and len(result.ops) == 3
    assert {p.name: p.read_text() for p in folder.iterdir()} == {
        "photo.jpg": "a.jpg", "photo (1).jpg": "b.jpg", "photo (2).jpg": "c.jpg"}

    assert history.rollback(history.batches[-1]).ok
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg", "c.jpg"]


def test_names_already_on_disk_are_skipped(tmp_path):
    # photo.jpg and photo (1).jpg already exist and are not part of the rename
    files(tmp_path, "photo.jpg", "photo (1).jpg")
    paths = files(tmp_path, "x.jpg", "y.jpg")
    rows = RenameEngine(all_to_photo(), auto_number=True).preview(paths)
    assert [r.proposed for r in rows] == ["photo (2).jpg", "photo (3).jpg"]
    assert RenameEngine(all_to_photo(), auto_number=True).apply(paths).ok
    assert (tmp_path / "photo.jpg").read_text() == "photo.jpg"   # never overwritten


def test_names_freed_by_the_batch_can_be_reused(tmp_path):
    # b.jpg -> z.jpg frees "b.jpg", so a.jpg -> b.jpg needs no number
    paths = files(tmp_path / "f", "a.jpg", "b.jpg")
    engine = RenameEngine([RegexRule(pattern="^b$", replacement="z"), RegexRule(pattern="^a$", replacement="b")],
                          auto_number=True)
    rows = engine.preview(paths)
    assert [r.proposed for r in rows] == ["b.jpg", "z.jpg"]
    assert all(r.status == Status.PENDING for r in rows)
    assert engine.apply(paths).ok
    assert {p.name: p.read_text() for p in (tmp_path / "f").iterdir()} == {"b.jpg": "a.jpg", "z.jpg": "b.jpg"}
    # two files given the same new name in one go: the second is numbered
    rows = RenameEngine([ReplaceRule(find="b", replace="z")], auto_number=True).preview(
        files(tmp_path / "g", "b.txt", "z.txt"))
    assert [r.proposed for r in rows] == ["z (1).txt", "z.txt"]


def test_case_only_rename_is_not_numbered(tmp_path):
    paths = files(tmp_path, "photo.jpg")
    rows = RenameEngine([TemplateRule(template="PHOTO")], auto_number=True).preview(paths)
    assert rows[0].proposed == "PHOTO.jpg" and rows[0].status == Status.PENDING


def test_window_toggle(app, win, tmp_path):
    files(tmp_path / "lib", "a.jpg", "b.jpg")
    win.add_paths([tmp_path / "lib"])
    assert pump(app, lambda: len(win.model.items) == 2)
    win.set_rules(all_to_photo())
    assert pump(app, lambda: idle(win) and win.model.proposals[1].status == Status.ERROR)
    win.auto_number.setChecked(True)
    assert pump(app, lambda: idle(win) and win.model.proposals[1].new_name == "photo (1).jpg")
    assert win.model.proposals[1].status == Status.WARNING
    win.close()
    assert win.settings["auto_number"] is True   # remembered for next time
