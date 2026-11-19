"""Quick Recipes: cards while the rule list is empty, one click loads rules (and sorts)."""
from pathlib import Path

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.recipes import RECIPES
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)

BY_KEY = {r.key: r for r in RECIPES}


def run(key: str, folder: Path, *names: str) -> dict[str, str]:
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"")
    rows = RenameEngine(BY_KEY[key].make()).preview(sorted(folder.iterdir()))
    return {r.original: r.proposed for r in rows}


def test_clean_downloads_and_strip_endings(tmp_path):
    out = run("downloads", tmp_path / "d", "my_report%20final (1).pdf", "song - Copy.mp3", "a_b.c.txt")
    assert out == {"my_report%20final (1).pdf": "my report final.pdf", "song - Copy.mp3": "song.mp3",
                   "a_b.c.txt": "a b c.txt"}
    out = run("endings", tmp_path / "e", "Report - Copy (2).docx", "Live (1999).mp3")
    assert out["Report - Copy (2).docx"] == "Report.docx"


def test_recipes_are_fresh_rules_and_examples_are_shown():
    for rec in RECIPES:
        assert rec.make() and rec.make()[0] is not rec.make()[0]       # new, editable rules each time
        assert rec.example[0] != rec.example[1]


def test_cards_load_rules_sort_and_undo(app, win, tmp_path):
    assert win.rule_area.currentIndex() == 0                           # no rules: recipe cards
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "song - Copy.mp3").write_text("x")
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == 1)
    card, example = win.recipe_cards["endings"]
    assert "song - Copy.mp3  →  song.mp3" in card.toolTip()           # live example from the user's file
    card.click()
    assert win.rule_area.currentIndex() == 1 and len(win.rules) == 1
    assert pump(app, lambda: idle(win) and win.model.proposals[0].new_name == "song.mp3")
    win.undo_rules()
    assert win.rule_area.currentIndex() == 0 and win.rules == []
