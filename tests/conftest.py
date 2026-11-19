import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import alexed_bru.skills  # noqa: E402,F401

RACE_TEST = "test_copies_started_in_the_same_instant_hand_files_to_one_window"
RACE_COPIES = 3


def start_race_copies(name: str) -> list:
    """Start the helper copies for the Send To race test. They load Qt (~0.6 s) and then wait."""
    import os
    import subprocess
    root = Path(__file__).resolve().parent.parent
    return [subprocess.Popen([sys.executable, str(root / "tests" / "instance_race_helper.py"), name,
                              f"C:/file{i}.txt", str(RACE_COPIES - 1)], cwd=root, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             env={**os.environ, "PYTHONPATH": str(root)})
            for i in range(RACE_COPIES)]


def pytest_collection_finish(session):
    # Keep the fast suite under 15 s: when the race test is selected, its copies load Qt in the
    # background while the other tests run, instead of the test waiting for them.
    if sys.platform == "win32" and any(item.name == RACE_TEST for item in session.items):
        import uuid
        name = "AlexbedBRU-test-" + uuid.uuid4().hex[:8]
        session.config._race_copies = (name, start_race_copies(name))


def pytest_sessionfinish(session):
    for p in getattr(session.config, "_race_copies", ("", []))[1]:
        if p.poll() is None:  # the test didn't run (e.g. stopped early)
            p.kill()


def make_mp3(path: Path, **tags) -> Path:
    """Write a tiny valid MPEG-1 Layer III stream and tag it with ID3v2."""
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3

    frame = b"\xff\xfb\x90\x64" + b"\x00" * 413  # 128 kbps, 44.1 kHz -> 417-byte frames
    path.write_bytes(frame * 20)
    ID3().save(path)
    audio = EasyID3(path)
    for key, value in tags.items():
        audio[key] = value
    audio.save()
    return path


@pytest.fixture
def mp3_factory(tmp_path):
    return lambda name, **tags: make_mp3(tmp_path / name, **tags)
