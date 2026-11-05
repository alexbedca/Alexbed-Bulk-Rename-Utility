"""Large batch: really rename 10,000 files on disk, then undo them all.

Runs both through the engine (with the persistent history) and through the
real window, so the model, history dialog path and relocation logic are all
exercised at scale. Timings are printed with `pytest -s`.
"""
import os
import time
from pathlib import Path

import pytest

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.models import FileItem, Status
from alexed_bru.skills.rules import CaseRule, CounterRule, RegexRule
from test_ui import app, idle, pump, win  # noqa: F401  (shared window fixtures)

FOLDERS, PER_FOLDER = 20, 500  # 10,000 files

pytestmark = pytest.mark.slow


def build(root: Path) -> dict[str, bytes]:
    """Create the library; return {relative path: content} to verify nothing is lost."""
    snapshot = {}
    for f in range(FOLDERS):
        d = root / f"Album {f:02d}"
        d.mkdir(parents=True)
        for i in range(PER_FOLDER):
            name = f"{i} - track_{i} (live).mp3"
            data = f"{f}/{i}".encode()
            (d / name).write_bytes(data)
            snapshot[f"Album {f:02d}/{name}"] = data
    return snapshot


def state(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


RULES = [
    RegexRule(pattern=r"^\d+ - (.+?) \(live\)$", replacement=r"\1"),
    CaseRule(mode="title"),
    CounterRule(placement="prefix", separator=". ", padding=3, reset_per_folder=True),
]


def test_engine_renames_and_undoes_10k_files(tmp_path):
    lib = tmp_path / "lib"
    before = build(lib)
    assert len(before) == FOLDERS * PER_FOLDER

    history = History.load(tmp_path / "data" / "history.json")
    engine = RenameEngine([r.clone() for r in RULES], history=history)
    items = [FileItem(lib / rel) for rel in sorted(before)]

    t0 = time.perf_counter()
    proposals = engine.compute(items)
    t_preview = time.perf_counter() - t0
    assert all(p.status == Status.PENDING for p in proposals)
    assert len({(i.folder_key, p.new_name.casefold()) for i, p in zip(items, proposals)}) == len(items)

    ops = engine.plan(items, proposals)
    t0 = time.perf_counter()
    result = engine.apply_plan(ops, "large batch")
    t_apply = time.perf_counter() - t0
    assert result.ok, result.error

    after = state(lib)
    assert len(after) == len(before)                                  # nothing lost or duplicated
    assert sorted(after.values()) == sorted(before.values())          # every file's content intact
    assert "Album 00/001. Track_0.mp3" in after and "Album 19/500. Track_99.mp3" in after  # text order: ..._98, _99
    assert not any(".~abru-" in k for k in after)                     # no temp files left behind

    # Undo from a freshly loaded journal (as after an app restart)
    reloaded = History.load(tmp_path / "data" / "history.json")
    batch = reloaded.last_applied()
    assert batch is not None and len(batch.ops) == len(before)
    t0 = time.perf_counter()
    undo = reloaded.rollback(batch)
    t_undo = time.perf_counter() - t0
    assert undo.ok, undo.error
    assert state(lib) == before                                       # exact original names + contents

    print(f"\n10k files: preview {t_preview:.2f}s, apply {t_apply:.2f}s, undo {t_undo:.2f}s")
    # Generous ceilings so slow disks don't flake, but a regression to minutes fails.
    assert t_preview < 10 and t_apply < 120 and t_undo < 120


def test_window_renames_and_undoes_10k_files(app, win, tmp_path):
    lib = tmp_path / "lib"
    before = build(lib)
    win.recursive.setChecked(True)
    win.add_paths([lib])
    assert pump(app, lambda: len(win.model.items) == len(before) and idle(win), timeout=30)

    win.set_rules([r.clone() for r in RULES])
    assert pump(app, lambda: idle(win) and win.model.counts()[Status.PENDING] == len(before), timeout=30)
    assert win.apply_btn.text() == "Rename 10,000 files"

    t0 = time.perf_counter()
    win.apply()
    assert pump(app, lambda: win.model.counts()[Status.SUCCESS] == len(before), timeout=180)
    t_apply = time.perf_counter() - t0
    assert len(state(lib)) == len(before)
    assert all(i.path.exists() for i in win.model.items)              # model follows the disk

    batch = win.history.last_applied()
    t0 = time.perf_counter()
    assert win.rollback_batch(batch, redo=False)
    t_undo = time.perf_counter() - t0
    assert state(lib) == before
    assert all(i.path.exists() for i in win.model.items)
    assert pump(app, lambda: idle(win) and win.model.counts()[Status.PENDING] == len(before), timeout=30)

    print(f"\nwindow, 10k files: apply {t_apply:.2f}s, undo {t_undo:.2f}s")
    assert os.listdir(lib)  # sanity
