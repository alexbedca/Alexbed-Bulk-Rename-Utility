"""One window: a second launch hands its files to the running copy."""
import subprocess
import sys
import json
import struct
import uuid
from pathlib import Path

import pytest

from alexed_bru.ui import single_instance as si
from test_ui import app, pump, win  # noqa: F401  (shared window fixtures)

ROOT = Path(__file__).resolve().parent.parent


def unique() -> str:
    return "AlexbedBRU-test-" + uuid.uuid4().hex[:8]


def test_nobody_running_returns_false_quickly(app):
    assert si.send_to_running(["x"], unique()) is False


def test_name_is_per_user_and_per_copy(monkeypatch, tmp_path):
    a = si.server_name()
    monkeypatch.setattr(si, "app_root", lambda: tmp_path)
    assert si.server_name() != a and si.server_name().startswith("AlexbedBRU-")


def test_running_window_receives_files_and_comes_forward(app, win, tmp_path):
    (tmp_path / "sent.txt").write_text("x")
    name = unique()
    server = si.InstanceServer(name, parent=win)
    server.filesReceived.connect(win.receive_files)
    assert server.start()
    # A second launch, driven step by step without blocking so this one thread can serve both
    # ends (the blocking send_to_running is covered by the real two-process test below).
    from PySide6.QtNetwork import QLocalSocket
    client = QLocalSocket()
    client.connectToServer(name)
    assert pump(app, lambda: client.state() == QLocalSocket.ConnectedState, timeout=2)
    body = json.dumps({"paths": [str(tmp_path / "sent.txt"), str(tmp_path / "missing.txt")]}).encode()
    client.write(struct.pack(">I", len(body)) + body)
    reply = []
    client.readyRead.connect(lambda: reply.append(bytes(client.readAll())))
    assert pump(app, lambda: b"".join(reply).startswith(b"ok"), timeout=2)
    assert pump(app, lambda: [i.name for i in win.model.items] == ["sent.txt"])  # missing file ignored


@pytest.mark.slow
def test_two_real_processes(tmp_path):
    name = unique()
    script = ("import sys; from PySide6.QtCore import QCoreApplication, QTimer;"
              "from alexed_bru.ui.single_instance import InstanceServer;"
              "app = QCoreApplication([]); s = InstanceServer(sys.argv[1]); assert s.start();"
              "s.filesReceived.connect(lambda p: (print('GOT', *p, flush=True), app.quit()));"
              "print('READY', flush=True); QTimer.singleShot(15000, app.quit); app.exec()")
    server = subprocess.Popen([sys.executable, "-c", script, name], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        assert server.stdout.readline().strip() == "READY"
        client = subprocess.run([sys.executable, "-c",
                                 "import sys; from PySide6.QtCore import QCoreApplication;"
                                 "from alexed_bru.ui.single_instance import send_to_running;"
                                 "app = QCoreApplication([]); print(send_to_running(['C:/a.txt'], sys.argv[1]))",
                                 name], cwd=ROOT, capture_output=True, text=True, timeout=20)
        assert client.stdout.strip() == "True"
        assert server.stdout.readline().strip() == "GOT C:/a.txt"
    finally:
        server.wait(timeout=20)


def test_mutex_lets_exactly_one_copy_win():
    name = unique()
    assert si.claim_primary(name) is True     # first claim in this process
    handle = si._mutex_handle
    assert si.claim_primary(name) is False    # the mutex now exists: a second copy loses
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.CloseHandle(si._mutex_handle)
        ctypes.windll.kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="named mutex is Windows only")
def test_copies_started_in_the_same_instant_hand_files_to_one_window(request):
    """Explorer's Send To on many files: 3 real processes claim at the same moment.
    Exactly one opens a window; it listens only after 0.15 s, yet gets every other copy's file.
    (conftest starts the copies when collection ends, so they load Qt while other tests run.)"""
    from conftest import start_race_copies
    name, procs = getattr(request.config, "_race_copies", None) or (unique(), None)
    procs = procs or start_race_copies(name)
    for p in procs:                                   # all loaded and waiting...
        assert p.stdout.readline().strip() == "READY"
    for p in procs:                                   # ...then released together
        p.stdin.write("go\n")
        p.stdin.flush()
    results = [json.loads(p.communicate(timeout=20)[0].strip().splitlines()[-1]) for p in procs]
    winners = [r for r in results if r["first"]]
    assert len(winners) == 1
    assert all(r["handed"] for r in results if not r["first"])
    expected = sorted(f"C:/file{i}.txt" for i, r in enumerate(results) if not r["first"])
    assert winners[0]["got"] == expected
