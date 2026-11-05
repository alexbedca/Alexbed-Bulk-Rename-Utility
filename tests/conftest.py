import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import alexed_bru.skills  # noqa: E402,F401


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
