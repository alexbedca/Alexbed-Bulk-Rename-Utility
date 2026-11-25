# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leave out of the one-file exe the Qt and Pillow parts this app never uses.

A one-file exe unpacks everything to a temp folder at every start (and antivirus scans it), so
every MB left out makes start-up quicker. Used by build.ps1:  python tools/slim_spec.py <spec>

What goes, and why it is safe for this widgets-only app:
* opengl32sw.dll: software OpenGL for QML/3D when there is no GPU driver; widgets don't use it.
* Qt Quick/QML/PDF/OpenGL libraries: pulled in only by plugins below (PDF image format, the
  on-screen keyboard), not by QtWidgets.
* TLS and network-information plugins plus Qt's own OpenSSL copy: the app never goes online
  (its single-window check is a local pipe). Python's own ssl/hashlib DLLs stay.
* qdirect2d / qminimal platform plugins (qwindows is the one used; qoffscreen stays for tests).
* Pillow's AVIF codec: AVIF images aren't read.
"""
from __future__ import annotations

import sys
from pathlib import Path

DROP = [
    "pyside6/opengl32sw.dll",
    "pyside6/qt6quick*.dll", "pyside6/qt6qml*.dll", "pyside6/qt6pdf*.dll", "pyside6/qt6opengl*.dll",
    "pyside6/qt6virtualkeyboard*.dll",
    "pyside6/plugins/imageformats/qpdf.dll",
    "pyside6/plugins/platforminputcontexts/*",
    "pyside6/plugins/tls/*",
    "pyside6/plugins/networkinformation/*",
    "pyside6/plugins/platforms/qdirect2d.dll",
    "pyside6/plugins/platforms/qminimal.dll",
    "pyside6/plugins/generic/*",
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
    "pil/_avif*",
]

FILTER = '''
# ---- added by tools/slim_spec.py: leave out parts this app never uses (see that file) ----
import fnmatch as _fn
_DROP = {drop!r}
def _keep(entry):
    name = entry[0].replace("\\\\", "/").lower()
    return not any(_fn.fnmatch(name, pattern) for pattern in _DROP)
_before = len(a.binaries) + len(a.datas)
a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
print(f"slim_spec: left out {{_before - len(a.binaries) - len(a.datas)}} file(s)")
'''


def main(spec: str) -> None:
    path = Path(spec)
    text = path.read_text(encoding="utf-8")
    if "slim_spec.py" in text:
        return
    marker = "pyz = PYZ("
    if marker not in text:
        raise SystemExit(f"slim_spec: '{marker}' not found in {spec}")
    path.write_text(text.replace(marker, FILTER.format(drop=DROP) + "\n" + marker, 1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
