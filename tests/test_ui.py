"""Drives the real MainWindow offscreen: every control a user touches."""
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from alexed_bru import paths  # noqa: E402
from alexed_bru.core.models import Status  # noqa: E402
from alexed_bru.skills.base import RULE_REGISTRY  # noqa: E402
from alexed_bru.skills.rules import (CaseRule, CounterRule, InsertRule, RegexRule,  # noqa: E402
                                     ReplaceRule)


@pytest.fixture(scope="session")
def app():
    from alexed_bru.ui.theme import apply_theme
    qapp = QApplication.instance() or QApplication([])
    apply_theme(qapp)
    return qapp


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ALEXED_BRU_DATA", str(tmp_path / "data"))
    paths.data_dir.cache_clear()
    import alexed_bru.ui.main_window as mw
    monkeypatch.setattr(mw.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    w = mw.MainWindow()
    w.show()
    yield w
    w.close()
    paths.data_dir.cache_clear()


def pump(app, cond=None, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond is not None and cond():
            # let queued signals settle
            for _ in range(5):
                app.processEvents()
            return True
        time.sleep(0.01)
    return cond is None


def idle(w):
    return not w._preview_timer.isActive() and w._preview_job is None


def library(root: Path) -> Path:
    for rel in ("A/01 one.txt", "A/02 two.txt", "A/sub/03 three.txt", "B/10 ten.txt", "B/2 two.txt"):
        p = root / "lib" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel)
    return root / "lib"


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.rglob("*.txt"))


def load(app, w, folder, recursive=True):
    w.recursive.setChecked(recursive)
    w.add_paths([folder])
    assert pump(app, lambda: w.model.items and idle(w))


def statuses(w):
    return [p.status for p in w.model.proposals]


# ---------------------------------------------------------------------------
def test_empty_state_and_scan(app, win, tmp_path):
    lib = library(tmp_path)
    assert win.grid_stack.currentIndex() == 0  # drop hint
    win.recursive.setChecked(False)
    win.add_paths([lib])  # top folder holds only subfolders
    assert pump(app, lambda: win.status_text.text().startswith("Added"))
    assert win.model.items == [] and win.grid_stack.currentIndex() == 0
    load(app, win, lib / "A", recursive=False)
    assert [i.name for i in win.model.items] == ["01 one.txt", "02 two.txt"]
    win.clear_files()
    load(app, win, lib / "A", recursive=True)
    assert [i.name for i in win.model.items] == ["01 one.txt", "02 two.txt", "03 three.txt"]
    assert win.grid_stack.currentIndex() == 1
    load(app, win, lib / "A", recursive=True)  # duplicates are ignored
    assert len(win.model.items) == 3


def test_rules_preview_counts_and_apply_button(app, win, tmp_path):
    load(app, win, library(tmp_path))
    assert not win.apply_btn.isEnabled()
    win.add_rule(CaseRule)
    win.rules[0].mode = "upper"
    win._on_rule_edited()
    assert pump(app, lambda: idle(win) and Status.PENDING in statuses(win))
    assert win.apply_btn.isEnabled() and win.apply_btn.text() == "Rename 5 files"
    assert "5 to rename" in win.counts.text()


def test_rule_undo_redo_reorder_toggle_duplicate_delete(app, win):
    win.add_rule(CaseRule)
    win.add_rule(InsertRule)
    assert [r.TYPE for r in win.rules] == ["case", "insert"]
    win.stack.setCurrentRow(1)
    win.move_rule(-1)
    assert [r.TYPE for r in win.rules] == ["insert", "case"]
    win.duplicate_rule()
    assert len(win.rules) == 3
    win.delete_rule()
    assert len(win.rules) == 2
    win._on_rule_toggled(0, False)
    pump(app, timeout=0.2)
    assert win.rules[0].enabled is False

    win.stack.setCurrentRow(1)
    win.rules[1].mode = "lower"
    win._on_rule_edited()
    win._commit_snapshot()
    win.undo_rules()
    assert win.rules[1].mode == "title"
    win.redo_rules()
    assert win.rules[1].mode == "lower"
    for _ in range(10):
        win.undo_rules()
    assert win.rules == []
    win.redo_rules()
    assert [r.TYPE for r in win.rules] == ["case"]


def test_editor_builds_for_every_rule_type(app, win):
    for cls in RULE_REGISTRY.values():
        win.add_rule(cls)
        pump(app, timeout=0.05)
        assert win.editor.rule is win.rules[-1]
    assert len(win.rules) == len(RULE_REGISTRY)


def test_invalid_regex_shows_error_and_is_ignored(app, win, tmp_path):
    load(app, win, library(tmp_path))
    win.add_rule(RegexRule)
    win.rules[0].pattern = "(oops"
    win.editor.set_rule(win.rules[0])
    assert win.editor.error_label.text().startswith("Invalid pattern")
    win._on_rule_edited()
    assert pump(app, lambda: idle(win))
    assert all(s == Status.UNCHANGED for s in statuses(win))


def test_regex_highlighting(app, win, tmp_path):
    win.add_rule(RegexRule)
    win.rules[0].pattern = r"^(\d+) (\w+)"
    win.stack.setCurrentRow(0)
    win._update_highlighter()
    assert win.model.highlighter("01 one.txt") == [(0, 2, 1), (2, 3, 0), (3, 6, 2)]
    win.rules[0] = ReplaceRule(find="one")
    win.stack.populate(win.rules, 0)
    win._update_highlighter()
    assert win.model.highlighter("one-ONE.txt") == [(0, 3, 0), (4, 7, 0)]


def test_filter_include_exclude_and_sort(app, win, tmp_path):
    load(app, win, library(tmp_path))
    win.add_rule(ReplaceRule)
    win.rules[0].find, win.rules[0].replace = "two", "2"
    win._on_rule_edited()
    assert pump(app, lambda: idle(win) and Status.PENDING in statuses(win))

    def visible(mode, text=""):
        win.search.setText(text)
        win.filter_mode.setCurrentIndex(win.filter_mode.findData(mode))
        return win.proxy.rowCount()

    assert visible("all") == 5
    assert visible("changed") == 2
    assert visible("unchanged") == 3
    assert visible("all", "ten") == 1
    win.model.set_include([0, 1, 2, 3, 4], False)
    assert pump(app, lambda: idle(win))
    assert visible("excluded") == 5 and not win.apply_btn.isEnabled()
    win.model.set_include(range(5), True)
    assert pump(app, lambda: idle(win))
    visible("all")
    win.proxy.sort(2, Qt.AscendingOrder)  # natural order: "2 two" before "10 ten"
    order = [i.name for i in win.model.items if i.folder.name == "B"]
    assert order == ["2 two.txt", "10 ten.txt"]


def test_counter_follows_sorted_order(app, win, tmp_path):
    load(app, win, library(tmp_path) / "B")
    win.set_rules([CounterRule(placement="replace", padding=1)])
    win.proxy.sort(2, Qt.DescendingOrder)
    assert pump(app, lambda: idle(win) and Status.PENDING in statuses(win))
    assert [(i.name, p.new_name) for i, p in zip(win.model.items, win.model.proposals)] == \
        [("10 ten.txt", "1.txt"), ("2 two.txt", "2.txt")]


def test_apply_skips_errors_then_history_undo_redo(app, win, tmp_path):
    lib = library(tmp_path)
    load(app, win, lib / "B")
    # Remove digits -> " ten.txt" and " two.txt"; then make them collide on purpose.
    win.set_rules([RegexRule(pattern=r"^\d+ ", replacement=""), ReplaceRule(find="ten", replace="two")])
    assert pump(app, lambda: idle(win) and Status.ERROR in statuses(win))
    assert not win.apply_btn.isEnabled()  # both rows collide -> nothing appliable

    win.set_rules([RegexRule(pattern=r"^\d+ ", replacement="")])
    assert pump(app, lambda: idle(win) and Status.PENDING in statuses(win))
    win.apply()
    assert pump(app, lambda: Status.SUCCESS in statuses(win))
    assert names(lib / "B") == ["ten.txt", "two.txt"]
    assert "2 renamed" in win.counts.text()

    from alexed_bru.ui.main_window import HistoryDialog
    dlg = HistoryDialog(win)
    assert dlg.tree.topLevelItemCount() == 1 and dlg.undo_btn.isEnabled()
    dlg.undo_btn.click()
    assert names(lib / "B") == ["10 ten.txt", "2 two.txt"]
    assert dlg.redo_btn.isEnabled()
    dlg.redo_btn.click()
    assert names(lib / "B") == ["ten.txt", "two.txt"]
    # the model followed the files on disk
    assert sorted(i.name for i in win.model.items) == ["ten.txt", "two.txt"]


def test_apply_while_preview_pending_uses_fresh_names(app, win, tmp_path):
    lib = library(tmp_path)
    load(app, win, lib / "B")
    win.set_rules([CaseRule(mode="upper")])
    win.apply()  # timer still pending: must wait for the preview, then apply it
    assert pump(app, lambda: Status.SUCCESS in statuses(win))
    assert names(lib / "B") == ["10 TEN.txt", "2 TWO.txt"]


def test_presets_save_load_and_starters(app, win, tmp_path, monkeypatch):
    from alexed_bru.core import presets
    win.set_rules([RegexRule(pattern="a", replacement="b"), CounterRule(start=9)])
    target = tmp_path / "mine.json"
    presets.save(target, win.rules)
    win.clear_rules()
    win.load_preset(target)
    assert [r.TYPE for r in win.rules] == ["regex", "counter"] and win.rules[1].start == 9
    win._fill_presets_menu()
    texts = [a.text() for a in win.presets_menu.actions()]
    assert "Music: 01. Artist - Title" in texts
    starter = next(a for a in win.presets_menu.actions() if a.text() == "Music: tidy messy names")
    starter.trigger()
    assert [r.TYPE for r in win.rules] == ["remove", "trim", "case", "pad"]


def test_session_restored_on_restart(app, win, tmp_path):
    win.set_rules([InsertRule(text="X-")])
    win.close()
    from alexed_bru.ui.main_window import MainWindow
    again = MainWindow()
    try:
        assert [r.TYPE for r in again.rules] == ["insert"] and again.rules[0].text == "X-"
    finally:
        again.close()


def test_details_panel_shows_metadata(app, win, tmp_path):
    load(app, win, library(tmp_path) / "B")
    win.table.selectRow(0)
    win._show_details(win.table.currentIndex())
    top = win.details.topLevelItem(0)
    assert top.text(0) == "System" and top.childCount() > 5
    tags = [top.child(i).text(2) for i in range(top.childCount())]
    assert "<sys:size>" in tags


def test_remove_selected_files(app, win, tmp_path):
    load(app, win, library(tmp_path) / "A", recursive=False)
    win.table.selectRow(0)
    win.remove_selected_files()
    assert [i.name for i in win.model.items] == ["02 two.txt"]
