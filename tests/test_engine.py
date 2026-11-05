"""End-to-end tests on real files in a temp folder."""
import os
from pathlib import Path

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.models import Status
from alexed_bru.core.transaction import RenameOp, execute
from alexed_bru.core.validation import name_errors
from alexed_bru.skills.rules import CaseRule, RegexRule, ReplaceRule, TemplateRule


def touch(folder: Path, *names: str) -> list[Path]:
    paths = []
    for n in names:
        p = folder / n
        p.write_text(n, encoding="utf-8")
        paths.append(p)
    return paths


def test_name_errors():
    assert name_errors("ok.txt") == []
    assert any("Invalid" in e for e in name_errors("a:b?.txt"))
    assert any("reserved" in e for e in name_errors("CON.txt"))
    assert any("dot or space" in e for e in name_errors("file."))
    assert name_errors("   ") == ["Name is empty"]


def test_preview_flags_collisions_and_existing_files(tmp_path):
    paths = touch(tmp_path, "a1.txt", "a2.txt", "b.txt", "keep.txt")
    engine = RenameEngine([RegexRule(pattern=r"\d", replacement="")])
    rows = {r.original: r for r in engine.preview(paths)}
    assert rows["a1.txt"].status == Status.ERROR and "Duplicate" in rows["a1.txt"].message
    assert rows["b.txt"].status == Status.UNCHANGED

    engine = RenameEngine([ReplaceRule(find="b", replace="keep")])
    rows = {r.original: r for r in engine.preview(paths)}
    assert rows["b.txt"].status == Status.ERROR and "already exists" in rows["b.txt"].message


def test_preview_flags_invalid_characters(tmp_path):
    paths = touch(tmp_path, "song.mp3")
    rows = RenameEngine([ReplaceRule(find="o", replace="?")]).preview(paths)
    assert rows[0].status == Status.ERROR and "Invalid" in rows[0].message


def test_swap_is_safe_via_two_phase_commit(tmp_path):
    a, b = touch(tmp_path, "a.txt", "b.txt")
    result = execute([RenameOp(a, b), RenameOp(b, a)])
    assert result.ok
    assert a.read_text() == "b.txt" and b.read_text() == "a.txt"


def test_swap_passes_validation(tmp_path):
    paths = touch(tmp_path, "a.txt", "b.txt")
    rule = RegexRule(pattern=r"^([ab])$", replacement="X")
    # a->b and b->a expressed as two replace steps through a placeholder
    rows = RenameEngine([ReplaceRule(find="a", replace="#"), ReplaceRule(find="b", replace="a"),
                         ReplaceRule(find="#", replace="b")]).preview(paths)
    assert [r.proposed for r in rows] == ["b.txt", "a.txt"]
    assert all(r.status == Status.PENDING for r in rows), rows
    del rule


def test_case_only_rename(tmp_path):
    (p,) = touch(tmp_path, "song.mp3")
    engine = RenameEngine([CaseRule(mode="upper")])
    assert engine.preview([p])[0].status == Status.PENDING
    assert engine.apply([p]).ok
    assert os.listdir(tmp_path) == ["SONG.mp3"]


def test_failed_transaction_rolls_back(tmp_path):
    a, b = touch(tmp_path, "a.txt", "b.txt")
    ops = [RenameOp(a, tmp_path / "x.txt"), RenameOp(b, tmp_path / "missing_dir" / "y.txt")]
    result = execute(ops)
    assert not result.ok and result.rolled_back
    assert sorted(os.listdir(tmp_path)) == ["a.txt", "b.txt"]


def test_history_undo_redo_persists(tmp_path):
    data = tmp_path / "data"
    files = tmp_path / "files"
    files.mkdir()
    paths = touch(files, "one.txt", "two.txt")
    engine = RenameEngine([CaseRule(mode="upper")], history=History.load(data / "history.json"))
    assert engine.apply(paths).ok
    assert sorted(os.listdir(files)) == ["ONE.txt", "TWO.txt"]

    reloaded = History.load(data / "history.json")  # simulates an app restart
    batch = reloaded.last_applied()
    assert batch and reloaded.rollback(batch).ok
    assert sorted(os.listdir(files)) == ["one.txt", "two.txt"]
    assert reloaded.reapply(reloaded.next_redo()).ok
    assert sorted(os.listdir(files)) == ["ONE.txt", "TWO.txt"]


def test_smart_audio_tags(mp3_factory):
    p = mp3_factory("01 track.mp3", artist="AC/DC", title="Thunderstruck", tracknumber="3/10",
                    album="The Razors Edge", date="1990")
    engine = RenameEngine([TemplateRule(template="<track:2>. <artist> - <title> (<year>)")])
    (row,) = engine.preview([p])
    assert row.proposed == "03. AC-DC - Thunderstruck (1990).mp3"  # '/' sanitised
    assert row.status == Status.PENDING

    explicit = RenameEngine([TemplateRule(template="<audio:album> - <audio:track:3>")])
    assert explicit.preview([p])[0].proposed == "The Razors Edge - 003.mp3"


def test_smart_tags_fall_back_to_system_dates(tmp_path):
    (p,) = touch(tmp_path, "notes.txt")
    (row,) = RenameEngine([TemplateRule(template="<name> <date:%Y>")]).preview([p])
    assert row.proposed.startswith("notes 20")


def test_missing_tags_warn_and_keep_original(tmp_path, mp3_factory):
    p = mp3_factory("untagged.mp3")
    (row,) = RenameEngine([TemplateRule(template="<artist> - <title>")]).preview([p])
    assert row.proposed == "untagged.mp3"
    assert row.status == Status.UNCHANGED


def test_chain_and_cycle_use_temporary_hop(tmp_path):
    a, b, c = touch(tmp_path, "a.txt", "b.txt", "c.txt")
    # chain a->b->c->d and a 2-cycle in one batch, mixed with direct renames
    d = tmp_path / "d.txt"
    x, y = touch(tmp_path, "x.txt", "y.txt")
    ops = [RenameOp(a, b), RenameOp(b, c), RenameOp(c, d), RenameOp(x, y), RenameOp(y, x)]
    assert execute(ops).ok
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == {
        "b.txt": "a.txt", "c.txt": "b.txt", "d.txt": "c.txt", "y.txt": "x.txt", "x.txt": "y.txt"}


def test_parallel_failure_rolls_back_everything(tmp_path):
    srcs = touch(tmp_path, *[f"f{i:03d}.txt" for i in range(200)])
    ops = [RenameOp(p, p.with_name("new_" + p.name)) for p in srcs]
    ops[150] = RenameOp(srcs[150], tmp_path / "no_such_dir" / "x.txt")  # this one fails
    result = execute(ops, workers=8)
    assert not result.ok and result.rolled_back and not result.stuck
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in srcs)
