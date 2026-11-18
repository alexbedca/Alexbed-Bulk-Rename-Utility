import os
import sys
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Assuming your engine imports look similar to this:
# from engine import RenameEngine, FileItem, RenameRulePipeline

# ==============================================================================
# CROSS-PLATFORM CONTEXT MANAGER FOR EXCLUSIVE FILE LOCKING
# ==============================================================================
class LockerContext:
    """Safely locks a file exclusively across Windows and Unix/macOS systems."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.fp = None

    def __enter__(self):
        # Open file with raw append/write access
        self.fp = open(self.filepath, 'a')
        if sys.platform == 'win32':
            import msvcrt
            # Lock 1 byte from the start of the file exclusively without blocking
            msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            # Lock exclusively, non-blocking on Unix-based OS
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fp:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    self.fp.seek(0)
                    msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            self.fp.close()


# ==============================================================================
# TEST CASE 1: TRANSACTONAL LOCKED FILE INTERRUPT & ROLLBACK
# ==============================================================================
def test_locked_file_aborts_and_rolls_back_cleanly(tmp_path):
    """
    Validates that if a single file in a batch is locked by another app, 
    the engine catches PermissionError, halts, and restores previously changed files.
    """
    # 1. Setup 5 mock files inside a temp directory
    sandbox_dir = tmp_path / "lock_test"
    sandbox_dir.mkdir()
    
    files = []
    original_contents = {}
    for i in range(1, 6):
        f_path = sandbox_dir / f"track_{i:02d}.mp3"
        f_path.write_text(f"audio content {i}")
        files.append(f_path)
        original_contents[f_path.name] = f"audio content {i}"

    # 2. Define a simple transformation pipeline (e.g., prefixing with 'New_')
    # pipeline = RenameRulePipeline([SearchReplaceRule("track_", "New_")])
    # engine = RenameEngine(files, pipeline)
    
    # Mocking the engine interface behavior for structural illustration
    # Replace this with your actual engine invocation logic
    engine = MagicMock()
    
    # 3. Apply an OS lock on the 3rd file using our platform-agnostic locker
    locked_file = files[2]
    
    with LockerContext(locked_file):
        # 4. Attempt the batch rename execution
        # In your real engine, this should throw/handle an internal Exception
        # resulting in a broad engine.execute() returning False or raising PermissionError
        with pytest.raises((PermissionError, OSError)):
            # Simulating what your engine does internally when encountering the lock:
            # It modifies file 1 & 2, hits file 3, fails, then executes its undo routine.
            
            # --- Simulated Engine Failure Loop ---
            try:
                files[0].rename(sandbox_dir / "New_track_01.mp3")
                files[1].rename(sandbox_dir / "New_track_02.mp3")
                
                # File 3 will raise an exception because it's locked by the context manager
                os.rename(str(files[2]), str(sandbox_dir / "New_track_03.mp3"))
            except (PermissionError, OSError) as e:
                # Rollback files 1 and 2 back to original state
                if (sandbox_dir / "New_track_01.mp3").exists():
                    (sandbox_dir / "New_track_01.mp3").rename(files[0])
                if (sandbox_dir / "New_track_02.mp3").exists():
                    (sandbox_dir / "New_track_02.mp3").rename(files[1])
                raise e

    # 5. Assertions: Verify directory structural integrity
    # Ensure every single file is restored to its exact original name and location
    for i in range(1, 6):
        expected_path = sandbox_dir / f"track_{i:02d}.mp3"
        assert expected_path.exists(), f"File track_{i:02d}.mp3 was lost or left modified!"
        assert expected_path.read_text() == original_contents[expected_path.name]


# ==============================================================================
# TEST CASE 2: 10,000 FILE HIGH-SPEED SANDBOX STRESS TEST
# ==============================================================================
@pytest.mark.slow
def test_ten_thousand_file_performance_and_history_undo(tmp_path):
    """
    Generates 10k files on disk, executes a complex multi-stage template rename,
    verifies file system outputs, and fires a complete transaction undo rollback.
    """
    sandbox_dir = tmp_path / "stress_test_10k"
    sandbox_dir.mkdir()
    
    total_files = 10000
    
    # 1. High-speed raw batch file generation
    # Instead of overhead-heavy open(), use native os operations for quick touch
    for i in range(total_files):
        filename = f"document_archive_item_{i:05d}.tmp"
        filepath = os.path.join(sandbox_dir, filename)
        with open(filepath, 'wb') as f:
            pass # Creating fast 0-byte sandbox files

    # Verify all 10k files exist on disk
    generated_items = os.listdir(sandbox_dir)
    assert len(generated_items) == total_files

    # 2. Setup your real Engine components
    # file_paths = [Path(sandbox_dir / f) for f in generated_items]
    # pipeline = RenameRulePipeline([
    #     CounterRule(start=1, padding=5, prefix="Asset_"),
    #     ChangeCaseRule(style="UPPER")
    #     ExtensionRule(new_ext="dat")
    # ])
    # engine = RenameEngine(file_paths, pipeline)
    
    # 3. Simulate Engine executing Rename Actions on disk
    # Replace this simulation loop with your real engine execution call:
    # engine.execute()
    
    rename_mapping = {}
    for i in range(total_files):
        old_name = f"document_archive_item_{i:05d}.tmp"
        new_name = f"ASSET_{i+1:05d}.DAT"
        rename_mapping[old_name] = new_name
        
        os.rename(
            os.path.join(sandbox_dir, old_name),
            os.path.join(sandbox_dir, new_name)
        )

    # Validate that all 10k items have shifted to the proposed target state
    renamed_items = os.listdir(sandbox_dir)
    assert len(renamed_items) == total_files
    assert "ASSET_00001.DAT" in renamed_items
    assert "ASSET_10000.DAT" in renamed_items
    assert f"document_archive_item_{0:05d}.tmp" not in renamed_items

    # 4. Trigger History Module Undo Action
    # Replace this simulation with your structural tracking call:
    # engine.history.undo_last_batch()
    for old_name, new_name in rename_mapping.items():
        os.rename(
            os.path.join(sandbox_dir, new_name),
            os.path.join(sandbox_dir, old_name)
        )

    # 5. Final Assertions: Ensure cryptographic/structural parity with setup state
    final_items = os.listdir(sandbox_dir)
    assert len(final_items) == total_files
    assert f"document_archive_item_{0:05d}.tmp" in final_items
    assert "ASSET_00001.DAT" not in final_items
