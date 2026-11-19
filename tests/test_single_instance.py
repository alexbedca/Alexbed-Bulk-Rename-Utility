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
