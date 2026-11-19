# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""One window: a second launch (e.g. Explorer's Send To) hands its files to the running app.

Uses a local named pipe (QLocalServer), never the network. The name includes the Windows
user and this copy's folder, so two portable copies don't talk to each other. If anything
fails, the new launch simply opens its own window: files are never lost.

Message: 4-byte big-endian length + UTF-8 JSON {"paths": [...]}; reply b"ok".

Race: Explorer's Send To on many files can start several copies in the same millisecond, before
the first one listens. So, before Qt starts, each copy claims a named Windows mutex: exactly one
gets it and becomes the window; the others keep trying to hand over their files for a few
seconds while that window starts listening (see `claim_primary` / `hand_off`).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import struct
import sys
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from alexed_bru.paths import app_root


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    seed = f"{user}|{os.path.normcase(str(app_root()))}".encode()
    return "AlexbedBRU-" + hashlib.sha1(seed).hexdigest()[:16]


_mutex_handle = None  # held for the life of the process; Windows frees it when the process ends
ERROR_ALREADY_EXISTS = 183


def claim_primary(name: str | None = None) -> bool:
    """True if this copy is the first one (it should open the window). Call before Qt starts.

    Uses a per-user, per-folder named mutex, so two copies started in the same millisecond
    can't both win. Off Windows, or if the mutex can't be made, every copy counts as first
    (the old behaviour: the socket check still catches a copy that is already listening).
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, "Local\\" + (name or server_name()))
        error = ctypes.get_last_error()
    except Exception:  # noqa: BLE001
        return True
    if not handle:
        return True
    _mutex_handle = handle  # keep it open (also when it already existed: harmless)
    return error != ERROR_ALREADY_EXISTS


def hand_off(paths: list[str], name: str | None = None, wait_s: float = 3.0, step_s: float = 0.075) -> bool:
    """Keep trying to give `paths` to the first copy while it starts listening. True if it took them."""
    deadline = time.monotonic() + wait_s
    while True:
        if send_to_running(paths, name):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(step_s)


def _allow_foreground() -> None:
    """Let the running copy bring its window to the front (Windows only allows that with consent)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:  # noqa: BLE001
            pass


def send_to_running(paths: list[str], name: str | None = None, timeout_ms: int = 2000) -> bool:
    """Hand `paths` to a running copy. True if it took them (this launch can then exit)."""
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(300):  # nobody running: fast
        return False
    _allow_foreground()
    body = json.dumps({"paths": list(paths)}).encode("utf-8")
    sock.write(struct.pack(">I", len(body)) + body)
    if not sock.waitForBytesWritten(timeout_ms):
        sock.abort()
        return False
    reply = b""
    while len(reply) < 2:
        # The reply may already be here: waitForReadyRead only waits for *new* data.
        if not sock.bytesAvailable() and not sock.waitForReadyRead(timeout_ms):
            break
        reply += bytes(sock.readAll())
    sock.disconnectFromServer()
    return reply.startswith(b"ok")


class InstanceServer(QObject):
    """Listens for later launches and emits the files they pass."""

    filesReceived = Signal(list)

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name or server_name()
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        self._buffers: dict[QLocalSocket, bytes] = {}

    def start(self) -> bool:
        if self.server.listen(self.name):
            return True
        QLocalServer.removeServer(self.name)  # left over from a crash
        return self.server.listen(self.name)

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self._buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: (self._buffers.pop(s, None), s.deleteLater()))

    def _read(self, sock: QLocalSocket) -> None:
        data = self._buffers.get(sock, b"") + bytes(sock.readAll())
        self._buffers[sock] = data
        if len(data) < 4:
            return
        (size,) = struct.unpack(">I", data[:4])
        if len(data) < 4 + size:
            return
        try:
            paths = json.loads(data[4:4 + size].decode("utf-8")).get("paths", [])
        except (ValueError, AttributeError):
            paths = None
        sock.write(b"ok" if paths is not None else b"no")
        sock.flush()
        if paths is not None:
            self.filesReceived.emit([str(p) for p in paths])
