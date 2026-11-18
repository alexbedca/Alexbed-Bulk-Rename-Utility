"""Locked files and a 10,000-file batch, run through the real RenameEngine.

A file held open by another program cannot be renamed on Windows. The engine
must then undo every rename it already did in that batch, leave no temporary
files behind, and record nothing in History.
"""
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from alexed_bru.core.engine import RenameEngine
from alexed_bru.core.history import History
from alexed_bru.core.transaction import WORKERS
from alexed_bru.skills.rules import CaseRule, CounterRule, ExtensionRule, PrefixSuffixRule, ReplaceRule

windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="only Windows blocks renaming a file that is open elsewhere")

# The other process opens the file normally (no delete sharing), as most apps
# do, says "ready", then holds it until its stdin closes.
_HOLDER = "import sys; f = open(sys.argv[1], 'rb'); print('ready', flush=True); sys.stdin.read()"


@contextmanager
def held_open_by_another_process(path: Path):
    proc = subprocess.Popen([sys.executable, "-c", _HOLDER, str(path)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        yield proc
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def snapshot(folder: Path) -> dict[str, bytes]:
    """Every file in the folder (recursively) with its content."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def make_files(folder: Path, names: list[str]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        p = folder / name
        p.write_bytes(f"content of {name}".encode())
        paths.append(p)
    return paths


def assert_rolled_back(result, folder: Path, before: dict[str, bytes], history: History) -> None:
    assert not result.ok
    assert result.rolled_back and result.stuck == []
    assert "PermissionError" in result.error or "WinError 32" in result.error
    assert snapshot(folder) == before                      # every name and byte as it was
    assert not list(folder.glob(".~abru-*"))               # no temporary names left over
    assert history.batches == [] and not history.path.exists()  # nothing to undo


# ==============================================================================
# 1. A locked file in a small batch: renames before it are undone
# ==============================================================================
@windows_only
def test_file_locked_by_another_process_rolls_back_the_whole_batch(tmp_path):
    folder = tmp_path / "lock_test"
    paths = make_files(folder, [f"track_{i:02d}.mp3" for i in range(1, 6)])
    before = snapshot(folder)
    history = History(tmp_path / "data" / "history.json")
    engine = RenameEngine([ReplaceRule(find="track_", replace="New_")], history=history)

    preview = engine.preview(paths)
    assert [r.proposed for r in preview] == [f"New_{i:02d}.mp3" for i in range(1, 6)]

    # The third file is locked: the first two are renamed, then the third fails.
    with held_open_by_another_process(paths[2]):
        result = engine.apply(paths)
    assert_rolled_back(result, folder, before, history)

    # Once the other program lets go, the same batch goes through and is journalled.
    result = engine.apply(paths)
    assert result.ok and len(result.ops) == 5
    assert sorted(snapshot(folder)) == [f"New_{i:02d}.mp3" for i in range(1, 6)]
    assert len(history.batches) == 1


# ==============================================================================
# 2. A locked file in a large chained batch: parallel steps and temp names undone
# ==============================================================================
@windows_only
def test_lock_in_large_chained_batch_rolls_back_parallel_steps(tmp_path):
    # file 001 -> file 002, file 002 -> file 003, ...: every target is occupied by
    # another file in the batch, so every file first moves to a temporary name.
    count = 100
    assert count > 64  # large enough for the engine's parallel workers
    folder = tmp_path / "chain"
    paths = make_files(folder, [f"file {i:03d}.txt" for i in range(1, count + 1)])
    before = snapshot(folder)
    history = History(tmp_path / "data" / "history.json")
    engine = RenameEngine([CounterRule(placement="renumber_first", start=2, padding=3)], history=history)

    preview = engine.preview(paths)
    assert preview[0].proposed == "file 002.txt" and preview[-1].proposed == f"file {count + 1:03d}.txt"

    with held_open_by_another_process(paths[count // 2]):
        result = engine.apply(paths)
    assert WORKERS > 1
    assert_rolled_back(result, folder, before, history)


# ==============================================================================
# 3. 10,000 files: multi-rule rename, journal survives a restart, undo restores all
# ==============================================================================
@pytest.mark.slow
def test_ten_thousand_files_rename_and_undo_through_history(tmp_path):
    total = 10_000
    folder = tmp_path / "stress_test_10k"
    paths = make_files(folder, [f"document_archive_item_{i:05d}.tmp" for i in range(total)])
    before = snapshot(folder)
    journal = tmp_path / "data" / "history.json"

    rules = [CounterRule(placement="replace", start=1, padding=5),   # 00001
             PrefixSuffixRule(prefix="Asset_"),                     # Asset_00001
             CaseRule(mode="upper"),                                # ASSET_00001
             ExtensionRule(mode="set", value="DAT")]                # ASSET_00001.DAT
    engine = RenameEngine(rules, history=History(journal))
    result = engine.apply(paths)
    assert result.ok and len(result.ops) == total

    after = snapshot(folder)
    assert sorted(after) == [f"ASSET_{i:05d}.DAT" for i in range(1, total + 1)]
    # each file kept its own content under its new name
    for op in result.ops:
        assert after[op.dst.name] == before[op.src.name]

    # Undo from a fresh History, as after restarting the app.
    history = History.load(journal)
    assert len(history.batches) == 1 and len(history.batches[0].ops) == total
    undo = history.rollback(history.batches[0])
    assert undo.ok
    assert snapshot(folder) == before
    assert History.load(journal).batches[0].undone
