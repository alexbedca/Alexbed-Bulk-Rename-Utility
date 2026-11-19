"""Privacy: the app writes no log files, and its data folder holds only user-facing data."""
import logging
import re
from pathlib import Path

from alexed_bru.core import duplicates as dup
from alexed_bru.core import flatten as fl
from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.skills.rules import ReplaceRule
from test_ui import app, pump, win  # noqa: F401  (shared window fixtures)

SOURCE = Path(__file__).resolve().parent.parent / "alexed_bru"
ALLOWED_DATA = {"history.json", "settings.json", "presets"}


def test_no_file_logging_in_the_code():
    pattern = re.compile(r"FileHandler|RotatingFileHandler|basicConfig\([^)]*filename|faulthandler\.enable\(.*file"
                         r"|\.log['\"]")
    hits = [f"{p.name}: {line.strip()}" for p in SOURCE.rglob("*.py")
            for line in p.read_text(encoding="utf-8").splitlines() if pattern.search(line)]
    assert hits == []


def test_rename_flatten_and_duplicates_write_no_logs(tmp_path):
    data = tmp_path / "AlexbedBRU_data"
    history = History(data / "history.json")
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    for name in ("a.txt", "b.txt", "sub/c.txt", "sub/copy.txt"):
        (work / name).write_text("same" if "c" in name else name)

    # rename + undo
    result = RenameEngine([ReplaceRule(find="a", replace="z")], history=history).apply([work / "a.txt"])
    assert result.ok and history.rollback(history.batches[-1]).ok
    # flatten + undo
    plan = fl.plan_flatten(work)
    assert fl.apply_flatten(plan, history).ok and history.rollback(history.batches[-1]).ok
    # duplicates move + undo
    groups = dup.find_duplicates(work.rglob("*.txt"))
    assert dup.move_to_folder([p for g in groups for p in g.extras], history).ok
    assert history.rollback(history.batches[-1]).ok

    logs = [p for p in tmp_path.rglob("*") if p.suffix.lower() == ".log" or "log" in p.suffix.lower()]
    assert logs == []
    assert {p.name for p in data.iterdir()} <= ALLOWED_DATA
    app_handlers = [h for h in logging.getLogger().handlers if not type(h).__module__.startswith("_pytest")]
    assert not any(isinstance(h, logging.FileHandler) for h in app_handlers)   # pytest adds its own


def test_clear_history(app, win, tmp_path, monkeypatch):
    from alexed_bru.ui import main_window as mw
    (tmp_path / "f.txt").write_text("x")
    RenameEngine([ReplaceRule(find="f", replace="g")], history=win.history).apply([tmp_path / "f.txt"])
    assert win.history.batches
    dlg = mw.HistoryDialog(win)
    monkeypatch.setattr(mw.QMessageBox, "question", staticmethod(lambda *a, **k: mw.QMessageBox.Yes))
    dlg.clear_btn.click()
    assert win.history.batches == [] and dlg.tree.topLevelItemCount() == 0
    assert History.load(win.history.path).batches == []          # saved, not just in memory
    assert (tmp_path / "g.txt").exists()                          # files are not touched
