# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
r"""README screenshots from the real window, over test_library (git-ignored sample files).

Run from the project folder before every release (they show the current UI):
    .venv\Scripts\python tools\make_screenshots.py
Writes docs/screenshots/*.png and video/build/hdr-flatten.png (used by make_tutorial_video.py).
"""
import os
import shutil
import sys

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LIB = ROOT / "test_library"
OUT = ROOT / "docs" / "screenshots"
os.environ["ALEXBED_BRU_DATA"] = str(LIB / ".appdata")

# Demo folders (inside the git-ignored test_library)
dups = LIB / "Duplicates demo"
hol = LIB / "Holiday photos"
for d in (dups, hol):
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
photo = (LIB / "Photos" / "IMG_0001.JPG").read_bytes()
photo2 = (LIB / "Photos" / "IMG_0002.JPG").read_bytes() + b"second photo"  # the two samples are identical
song = next((LIB / "Music" / "ACDC" / "Back In Black").glob("1 - *")).read_bytes()
for name, data in [("IMG_0001.JPG", photo), ("IMG_0001 (1).JPG", photo), ("Holiday beach.JPG", photo),
                   ("IMG_0002.JPG", photo2), ("IMG_0002 - Copy.JPG", photo2),
                   ("hells bells.mp3", song), ("hells bells - Copy.mp3", song), ("notes.txt", b"unique")]:
    (dups / name).write_bytes(data)
for name in ("IMG_0412.jpg", "IMG_0413.jpg", "IMG_0414.jpg", "IMG_0415.jpg", "beach_sunset.jpg"):
    (hol / name).write_bytes(photo)
(hol / "Holiday.jpg").write_bytes(photo2)
folders_demo = LIB / "Folder demo"
shutil.rmtree(folders_demo, ignore_errors=True)
for rel in ("the beatles/abbey road (1969)", "the beatles/let it be (1970)", "pink floyd/the wall (1979)",
            "pink floyd/wish you were here (1975)"):
    (folders_demo / rel).mkdir(parents=True)

from PySide6.QtCore import QEvent, QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402
from alexed_bru.ui.theme import apply_theme  # noqa: E402

app = QApplication([])
apply_theme(app)
from alexed_bru.skills.rules import (CaseRule, PadNumbersRule, RegexRule, TemplateRule,  # noqa: E402
                                     TrimRule)
from alexed_bru.ui.main_window import MainWindow  # noqa: E402
from alexed_bru.ui.preview_model import COL_NEW  # noqa: E402


def pump(sec=0.8, cond=None):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        if cond and cond():
            break
        time.sleep(0.01)
    for _ in range(10):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def window(paths, rules, select=0, auto=False):
    w = MainWindow()
    w.resize(1400, 800)
    w.recursive.setChecked(True)
    w.auto_number.setChecked(auto)
    w.show()
    w.clear_files()
    w.add_paths(paths)
    pump(3, lambda: w.model.items)
    pump(0.5)
    w.set_rules(rules)
    w.stack.setCurrentRow(select)
    pump(1.5)
    w.table.selectRow(min(2, len(w.model.items) - 1))
    pump(0.5)
    return w


def save(widget, name):
    pump(0.3)
    widget.grab().save(str(OUT / name))
    print("saved", name)


messy = [LIB / "Messy names", LIB / "Music" / "ACDC"]

# 1. main window: a clean-up pipeline with plain-English rule cards
w = window(messy, [RegexRule(**RegexRule.EXAMPLES[3][2]), TrimRule(), PadNumbersRule(),
                   CaseRule(mode="smart_title")], select=3)
save(w, "main-window.png")
w.close()

# 2. RegEx capture groups highlighted
w = window(messy, [RegexRule(pattern=r"^(\d+) - (.+?) \((.+)\)$", replacement=r"\1. \2")])
save(w, "regex-groups.png")

# 3. Examples menu
examples = next(b for b in w.editor.findChildren(QToolButton) if b.text() == "Examples")
menu = examples.menu()
menu.popup(examples.mapToGlobal(QPoint(0, examples.height())))
pump(0.6)
save(menu, "regex-examples.png")
menu.close()

# 4. RegEx guide
from alexed_bru.ui.regex_help import RegexGuide  # noqa: E402
guide = RegexGuide(w)
guide.show()
pump(0.6)
save(guide, "regex-guide.png")
guide.close()
w.close()

# 5. RegEx from example
w = window([LIB / "Music" / "ACDC"], [RegexRule()])
ed = w.editor
ed.gen_toggle.setChecked(True)
pump(0.3)
ed.gen_sample.setEditText("1 - hells bells (official audio).mp3")
ed.gen_desired.setText("hells bells - 1")
pump(1)
save(w, "regex-from-example.png")
w.close()

# 6. Smart tags
w = window([LIB / "Music"], [TemplateRule(template="<track:2>. <artist> - <title>")])
save(w, "smart-tags.png")
w.close()

# 7. Auto-number + a hand-typed name
w = window([hol], [TemplateRule(template="Holiday", fallback_to_original=False)], auto=True)
row = next(n for n, i in enumerate(w.model.items) if i.name == "beach_sunset.jpg")
w.model.setData(w.model.index(row, COL_NEW), "Sunset on the beach.jpg")
pump(1.5)
w.table.selectRow(row)
pump(0.3)
save(w, "auto-number-and-edit.png")
w.close()

# 7b. Quick recipe cards
w = window([LIB / "Music"], [])
save(w, "recipes.png")
w.close()

# 7c. Folder renaming mode: an artist folder and its album folders together
w = MainWindow()
w.resize(1400, 800)
w.show()
w.set_folder_mode(True)
w.add_paths([folders_demo], contents=True)
pump(3, lambda: len(w.model.items) == 6)
w.set_rules([CaseRule(mode="title")])
pump(1.5)
w.table.selectRow(1)
pump(0.5)
save(w, "folder-mode.png")
w.close()

# 8. Find duplicates dialog
w = window([dups], [])
from alexed_bru.ui.duplicates_dialog import DuplicatesDialog  # noqa: E402
dlg = DuplicatesDialog(w, [i.path for i in w.model.items])
dlg.resize(900, 520)
dlg.show()
pump(5, lambda: dlg._job is None)
save(dlg, "duplicates.png")
dlg.close()
w.close()
# 9. Flatten dialog (and the header picture the video uses)
demo = LIB / "Flatten demo" / "Playlist"
shutil.rmtree(demo.parent, ignore_errors=True)
song = next((LIB / "Music" / "ACDC" / "Back In Black").glob("1 - *")).read_bytes()
for rel in ("AC-DC/Back In Black/01 Hells Bells.mp3", "AC-DC/Back In Black/02 Shoot to Thrill.mp3",
            "AC-DC/Back In Black/cover.jpg", "Adele/25/01 Hello.mp3", "Adele/25/cover.jpg",
            "Adele/21/01 Rolling in the Deep.mp3", "Adele/21/cover.jpg", "Nina Simone/Feeling Good.mp3",
            "Nina Simone/Thumbs.db"):
    p = demo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(song + rel.encode())
(demo / "_Duplicates").mkdir()
(demo / "_Duplicates" / "old copy.mp3").write_bytes(b"x")
build = ROOT / "video" / "build"
build.mkdir(parents=True, exist_ok=True)
from alexed_bru.ui.flatten_dialog import FlattenDialog  # noqa: E402
w = MainWindow()
w.resize(1400, 800)
w.show()
w.clear_files()
pump(0.5)
w.grab().save(str(build / "hdr-flatten.png"))
d = FlattenDialog(w, demo)
d.resize(940, 560)
d.show()
pump(3, lambda: d.plan is not None)
pump(0.5)
d.grab().save(str(ROOT / "docs" / "screenshots" / "flatten.png"))
print(d.summary.text())
d.close()
w.close()
print("done")

