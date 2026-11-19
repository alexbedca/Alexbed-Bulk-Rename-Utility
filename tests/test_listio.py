"""Export the list to CSV/TXT and import edited names back as typed names."""
import csv
from pathlib import Path

from alexed_bru.core import listio
from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.models import FileItem, Proposal, Status
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)


def files(folder: Path, *names: str) -> list[FileItem]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        (folder / n).write_text(n)
        out.append(FileItem(folder / n))
    return out


def test_formula_cells_are_neutralised_and_restored():
    for text in ("=HYPERLINK(\"x\")", "+1", "-intro.mp3", "@cmd", "\tx"):
        assert listio.safe_cell(text) == "'" + text
        assert listio.unsafe_cell(listio.safe_cell(text)) == text
    assert listio.safe_cell("Song.mp3") == "Song.mp3"
    assert listio.unsafe_cell("'Quoted name.mp3") == "'Quoted name.mp3"   # a real leading ' stays


def test_csv_round_trip_with_excel_style_edits(tmp_path):
    items = files(tmp_path / "Music", "a.mp3", "=evil.mp3", "c.mp3")
    props = [Proposal("A.mp3", Status.PENDING), Proposal("=evil.mp3"), Proposal("c.mp3")]
    out = tmp_path / "list.csv"
    assert listio.export_csv(out, items, props) == 3
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")                    # BOM for Excel
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0] == listio.HEADER and rows[2][1] == "'=evil.mp3"          # no live formula

    rows[1][2] = "Alpha.mp3"            # edit two names, as a user would in Excel
    rows[2][2] = "'=safe now.mp3"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh, delimiter=";").writerows(rows)                       # Excel in many locales saves with ;
    result = listio.import_list(out, items)
    assert result.problems == [] and result.unchanged == 1
    assert result.names == {0: "Alpha.mp3", 1: "=safe now.mp3"}


def test_csv_rows_that_dont_match_are_reported_not_guessed(tmp_path):
    items = files(tmp_path / "A", "same.txt") + files(tmp_path / "B", "same.txt", "only.txt")
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("Original name,New name\nsame.txt,x.txt\nonly.txt,y.txt\nmissing.txt,z.txt\n",
                        encoding="utf-8")
    result = listio.import_list(csv_file, items)
    assert result.names == {2: "y.txt"}
    assert len(result.problems) == 2 and "more than once" in result.problems[0]


def test_txt_formats(tmp_path):
    items = files(tmp_path, "a.txt", "b.txt")
    out = tmp_path / "list.txt"
    listio.export_txt(out, items, [Proposal("a.txt"), Proposal("b.txt")])
    out.write_text(out.read_text(encoding="utf-8-sig").replace("b.txt\tb.txt", "b.txt\tB2.txt"), encoding="utf-8")
    assert listio.import_list(out, items).names == {1: "B2.txt"}
    plain = tmp_path / "plain.txt"
    plain.write_text("first.txt\nsecond.txt\n", encoding="utf-8")
    assert listio.import_list(plain, items).names == {0: "first.txt", 1: "second.txt"}
    plain.write_text("only one.txt\n", encoding="utf-8")
    result = listio.import_list(plain, items)
    assert result.names == {} and "exactly one line per file" in result.problems[0]


def test_imported_names_rename_and_undo(tmp_path):
    items = files(tmp_path / "f", "a.txt", "b.txt")
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("Original name,New name\na.txt,b.txt\nb.txt,c.txt\n", encoding="utf-8")
    names = listio.import_list(csv_file, items).names
    history = History(tmp_path / "h.json")
    overrides = {items[i].path: n for i, n in names.items()}
    result = RenameEngine([], history=history).apply([i.path for i in items], overrides=overrides)
    assert result.ok                                               # a.txt -> b.txt while b.txt -> c.txt: a chain
    assert sorted(p.name for p in (tmp_path / "f").iterdir()) == ["b.txt", "c.txt"]
    assert history.rollback(history.batches[-1]).ok
    assert sorted(p.name for p in (tmp_path / "f").iterdir()) == ["a.txt", "b.txt"]


def test_window_import_and_reset(app, win, tmp_path):
    lib = tmp_path / "lib"
    files(lib, "one.txt", "two.txt")
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == 2)
    out = tmp_path / "list.csv"
    listio.export_csv(out, win.model.items, win.model.proposals)
    out.write_text(out.read_text(encoding="utf-8-sig").replace(",one.txt,one.txt,", ",one.txt,1st.txt,"),
                   encoding="utf-8")
    win.import_names(out)
    assert pump(app, lambda: idle(win) and win.model.proposals[0].new_name == "1st.txt")
    assert win.model.proposals[0].manual
    win.reset_all_typed()
    assert pump(app, lambda: idle(win) and win.model.proposals[0].new_name == "one.txt")


def test_rows_not_edited_in_the_sheet_stay_with_the_rules(tmp_path):
    items = files(tmp_path / "M", "a.mp3", "b.mp3", "c.mp3")
    csv_file = tmp_path / "in.csv"
    # a: rule-made name left as exported; b: edited by the user; c: typed earlier (manual)
    csv_file.write_text("Original name,New name\na.mp3,01 a.mp3\nb.mp3,My edit.mp3\nc.mp3,03 c.mp3\n",
                        encoding="utf-8")
    result = listio.import_list(csv_file, items, current=["01 a.mp3", "02 b.mp3", None])
    assert result.names == {1: "My edit.mp3", 2: "03 c.mp3"} and result.unchanged == 1
