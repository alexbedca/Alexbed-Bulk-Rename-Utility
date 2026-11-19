"""Explorer "Send to" shortcut. Every test uses a temporary folder, never the real SendTo folder."""
import sys
from pathlib import Path

import pytest

from alexed_bru.core import sendto
from test_ui import app, pump, win  # noqa: F401  (shared window fixtures)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows feature")


@pytest.fixture(autouse=True)
def fake_sendto(tmp_path, monkeypatch):
    """Point the module at a temporary folder so the real profile is never touched."""
    folder = tmp_path / "SendTo"
    monkeypatch.setattr(sendto, "sendto_dir", lambda: folder)
    return folder


def test_default_folder_is_the_users_sendto(monkeypatch):
    monkeypatch.undo()  # look at the real function, without creating anything
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert sendto.sendto_dir() == Path(r"C:\Users\x\AppData\Roaming\Microsoft\Windows\SendTo")


@pytest.mark.slow  # makes a real shortcut through PowerShell (~1.2 s); runs in the release check
def test_install_points_at_this_app_and_remove_deletes_only_it(fake_sendto):
    other = fake_sendto / "Mail recipient.MAPIMail"
    fake_sendto.mkdir()
    other.write_text("keep me")
    assert not sendto.is_installed()

    lnk = sendto.install()
    assert lnk == fake_sendto / sendto.SHORTCUT_NAME and sendto.is_installed()
    target, args = sendto.read_shortcut(lnk)
    expected_target, expected_args, _dir, _icon = sendto.launch_command()
    assert Path(target) == Path(expected_target)
    assert args == expected_args and args.endswith('run.py"')   # from source: pythonw "...run.py"

    sendto.remove()
    assert not sendto.is_installed() and other.read_text() == "keep me"
    sendto.remove()           # already gone: no error


def test_launch_command_for_the_portable_exe(monkeypatch, tmp_path):
    exe = tmp_path / "AlexbedBulkRename.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    target, args, workdir, icon = sendto.launch_command()
    assert (target, args, workdir) == (str(exe), "", str(tmp_path)) and icon == f"{exe},0"


def test_more_menu_toggle(app, win, fake_sendto, monkeypatch):
    # The real shortcut maker is tested above; here a stand-in keeps the run fast.
    def fake_install():
        fake_sendto.mkdir(exist_ok=True)
        return sendto.shortcut_path().write_bytes(b"lnk")
    monkeypatch.setattr(sendto, "install", fake_install)
    win._sync_more_menu()
    assert not win.sendto_action.isChecked()
    win.sendto_action.trigger()                 # tick
    assert sendto.is_installed() and win.sendto_action.isChecked()
    assert "Send To" in win.status_text.text()
    win.sendto_action.trigger()                 # untick
    assert not sendto.is_installed() and not win.sendto_action.isChecked()
