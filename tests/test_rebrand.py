"""1.1.1 renamed the app from the misspelt "Alexed" to "Alexbed": old data and shortcuts keep working."""
import pytest

from alexed_bru import APP_NAME, paths
from alexed_bru.core import sendto


@pytest.fixture
def clean(monkeypatch, tmp_path):
    for var in paths.ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def test_name():
    assert APP_NAME == "Alexbed Bulk Rename Utility"


def test_new_install_uses_the_new_folder(clean):
    assert paths.data_dir() == clean / "AlexbedBRU_data"


def test_existing_old_folder_is_kept(clean):
    old = clean / "AlexedBRU_data"
    old.mkdir()
    (old / "history.json").write_text("{}")
    assert paths.data_dir() == old              # history and settings are not lost


def test_new_folder_wins_when_both_exist(clean):
    (clean / "AlexedBRU_data").mkdir()
    (clean / "AlexbedBRU_data").mkdir()
    assert paths.data_dir() == clean / "AlexbedBRU_data"


@pytest.mark.parametrize("var", ["ALEXBED_BRU_DATA", "ALEXED_BRU_DATA"])
def test_both_environment_names_work(clean, monkeypatch, var):
    monkeypatch.setenv(var, str(clean / "custom"))
    assert paths.data_dir() == clean / "custom"


def test_old_send_to_shortcut_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(sendto, "sendto_dir", lambda: tmp_path)
    old = tmp_path / sendto.OLD_SHORTCUT_NAME
    old.write_bytes(b"lnk")
    sendto.remove()
    assert not old.exists()
