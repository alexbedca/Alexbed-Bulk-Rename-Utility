"""Helper for test_single_instance: one of several copies started at the same moment.

Usage: python instance_race_helper.py NAME PATH EXPECTED
Every copy imports Qt first, prints READY and waits for a line on stdin, so the test can
release them all at the same moment to claim the mutex together. The winner pretends its
window takes 0.15 s to build before it listens.
Prints one JSON line: {"first": bool, "handed": bool, "got": [...]}.
"""
import json
import sys

from PySide6.QtCore import QCoreApplication, QTimer

from alexed_bru.ui.single_instance import InstanceServer, claim_primary, hand_off

name, path, expected = sys.argv[1], sys.argv[2], int(sys.argv[3])
print("READY", flush=True)
sys.stdin.readline()
first = claim_primary(name)
app = QCoreApplication([])
if not first:
    print(json.dumps({"first": False, "handed": hand_off([path], name), "got": []}), flush=True)
    sys.exit(0)

got: list[str] = []
server = InstanceServer(name)


def received(paths):
    got.extend(paths)
    if len(got) >= expected:
        QTimer.singleShot(50, app.quit)  # let the last reply reach its sender


server.filesReceived.connect(received)
QTimer.singleShot(150, server.start)   # a slow window: listens only after 0.15 s
QTimer.singleShot(8000, app.quit)      # safety net
app.exec()
print(json.dumps({"first": True, "handed": False, "got": sorted(got)}), flush=True)
