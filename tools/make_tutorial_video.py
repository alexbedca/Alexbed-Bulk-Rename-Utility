# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the narrated how-to video: video/Alexbed-Bulk-Rename-Utility-how-to.mp4.

    .venv\\Scripts\\python tools\\make_tutorial_video.py

Steps: capture a few extra screens from the real window (uses test_library, git-ignored),
draw 1920x1080 slides with Pillow, speak each narration with a Windows voice
(tools\\tts.ps1), then join everything with ffmpeg and add soft subtitles.
Needs ffmpeg on PATH. Uses docs/screenshots for most steps.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "video"
BUILD = OUT / "build"
SHOTS = ROOT / "docs" / "screenshots"
W, H, FPS = 1920, 1080, 30
VOICE = os.environ.get("VIDEO_VOICE", "Mark")

# ---- storyboard ---------------------------------------------------------------
# image: file in docs/screenshots or a capture name; boxes: highlight rectangles in the
# image's own pixels ("menu" = the captured menu's rectangle).
SLIDES = [
    dict(kind="title", title="How to use it",
         say="Welcome! This short video shows how to rename hundreds of files safely with "
             "Alexbed Bulk Rename Utility. It's free, it's portable, and nothing changes on your disk "
             "until you press Rename."),
    dict(title="Start the app", image="cap-empty.png", boxes=[(12, 8, 1392, 52)],
         caption="Download AlexbedBulkRename.exe from GitHub and run it. No install needed.",
         say="Download Alexbed Bulk Rename dot E X E from the GitHub releases page, and run it. There's "
             "nothing to install. If Windows SmartScreen appears, choose More info, then Run anyway."),
    dict(title="Add your files", image="cap-files.png", boxes=[(240, 8, 600, 52)],
         caption="Drag files or folders onto the window, or use + Files and + Folder.",
         say="Drag files or folders onto the window, or use the Files and Folder buttons. Tick Include "
             "subfolders to add everything inside a folder."),
    dict(title="Add rules", image="cap-addrule.png", boxes=["menu"],
         caption="Click Add rule and choose what to change. Rules run from top to bottom.",
         say="Click Add rule, and pick what you want to do: replace text, change capitals, add numbers, "
             "and more. You can stack several rules. They run from top to bottom."),
    dict(title="Start from a recipe", image="recipes.png", boxes=[(12, 70, 392, 350)],
         caption="No rules yet? Pick a Quick Recipe: it shows what it does to your own file.",
         say="Not sure where to start? While the rule list is empty, it shows quick recipes: organize music, "
             "photos by date taken, clean web downloads, and strip copy endings. Each card shows what it would "
             "do to your own first file. One click loads the rules, and you can change them or undo."),
    dict(title="Put files in order before numbering", image="cap-sort.png", boxes=["menu"],
         caption="Sort by name, date taken, track number or size, or drag rows: numbers follow the list.",
         say="Numbers follow the order of the list. Use Sort by, for example date taken or track number, "
             "drag rows into place, or move the selected rows with Control and the arrow keys."),
    dict(title="Every rule explains itself", image="main-window.png", boxes=[(12, 70, 392, 350)],
         caption="Each rule card says in plain English what it does.",
         say="Each rule card tells you in plain English what it does. For example: pads numbers to two "
             "digits, or capitalises words. Untick a rule to switch it off, or drag it to change the order."),
    dict(title="See every change first", image="main-window.png", boxes=[(415, 158, 1390, 430)],
         caption="Added text is highlighted in blue. Removed text is struck through in red.",
         say="The preview updates as you type. Added text is highlighted in blue, and removed text is "
             "struck through in red. Nothing on your disk has changed yet."),
    dict(title="Reorder names without RegEx", image="regex-from-example.png", boxes=[(26, 522, 370, 755)],
         caption="RegEx Replace → From example: type how one name should look.",
         say="Want to reorder names, but don't know regular expressions? Add a Reg Ex Replace rule, click "
             "From example, and type how one file should look. The pattern is written for you, and it "
             "shows how many files it matches. Then click Use this pattern."),
    dict(title="Fix one file by hand", image="auto-number-and-edit.png", boxes=[(415, 158, 1390, 188)],
         caption="Double-click a new name (or press F2) and type your own.",
         say="To fix a single file, double-click its new name, or press F2, and type. A pencil marks names "
             "you typed yourself. To undo that, right-click and choose Reset to rule name."),
    dict(title="Duplicate names, numbered", image="auto-number-and-edit.png",
         boxes=[(742, 85, 960, 113), (415, 218, 1390, 340)],
         caption="Tick Auto-number duplicate names: photo (1), photo (2)…",
         say="If two files would end up with the same name, they show in red and are skipped. Tick "
             "Auto-number duplicate names, and they become photo one, photo two, and so on. Files that "
             "are already in the folder are never overwritten."),
    dict(title="Rename, and undo any time", image="cap-history.png", boxes=[(8, 70, 812, 94), (528, 374, 650, 410)],
         caption="Click Rename files. History can undo any batch, even after a restart.",
         say="When the preview looks right, click Rename files. Every batch is saved in History, so you "
             "can undo it at any time, even after closing the app. If anything fails halfway, every file "
             "is put back automatically."),
    dict(title="Find duplicate files", image="duplicates.png", boxes=[(10, 110, 890, 325)],
         caption="Duplicates finds identical files, even with different names.",
         say="Click Duplicates to find files with exactly the same content, even when their names are "
             "different. The original is kept, and the copies are ticked. Move them to a Duplicates "
             "folder, which you can undo, or to the Recycle Bin."),
    dict(title="Flatten a folder", image="flatten.png", boxes=[(8, 172, 932, 422)],
         caption="Flatten moves every file out of the subfolders into one folder.",
         say="Got music spread over artist and album folders? Click Flatten and choose the folder. The "
             "preview shows where every file goes. Files with the same name get a number or the folder name, "
             "and the empty subfolders are removed. Like everything else, you can undo it from History, and "
             "the files can go straight into the rename list."),
    dict(title="Names from music and photo tags", image="smart-tags.png", boxes=[(26, 470, 378, 525)],
         caption="Templates like <track:2>. <artist> - <title> use the files' own tags.",
         say="Music, photos, videos and documents carry tags. A template such as track, artist, title "
             "builds tidy names from them automatically."),
    dict(title="Spreadsheet and Send To", image="cap-more.png", boxes=["menu"],
         caption="••• menu: export and import name lists, or add the app to Explorer's Send To.",
         say="In the three dots menu, you can export the list to a spreadsheet, type new names there, and "
             "import them back. You can also add the app to Windows' Send To menu: files you send go "
             "straight into the open window."),
    dict(kind="end", title="Happy renaming!",
         say="That's it! Download Alexbed Bulk Rename Utility free from GitHub. Happy renaming!"),
]

BG, PANEL, CYAN, VIOLET, INDIGO = (11, 13, 26), (17, 20, 42), (34, 211, 238), (192, 132, 252), (99, 102, 241)
TEXT, DIM, FAINT = (226, 232, 240), (170, 178, 204), (120, 128, 160)


# ---- 1. captures from the real window -----------------------------------------
def capture() -> dict:
    lib = ROOT / "test_library"
    demo = lib / "Video demo"
    shutil.rmtree(demo, ignore_errors=True)
    shutil.copytree(lib / "Messy names", demo)
    data = BUILD / "appdata"
    shutil.rmtree(data, ignore_errors=True)
    os.environ["ALEXBED_BRU_DATA"] = str(data)

    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtWidgets import QApplication, QMessageBox
    from alexed_bru.ui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    from alexed_bru.skills.rules import CaseRule, TrimRule
    from alexed_bru.ui.main_window import HistoryDialog, MainWindow
    from alexed_bru.ui.rule_editor import rules_menu

    def pump(sec=0.6, cond=None):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            if cond and cond():
                break
            time.sleep(0.01)
        for _ in range(10):
            app.processEvents()

    meta = {}

    def with_menu(w, menu, at: QPoint, name):
        win_img = w.grab()
        menu.popup(w.mapToGlobal(at))
        pump(0.5)
        menu_img = menu.grab()
        offset = menu.pos() - w.mapToGlobal(QPoint(0, 0))
        menu.close()
        a, b = BUILD / "tmp-win.png", BUILD / "tmp-menu.png"
        win_img.save(str(a))
        menu_img.save(str(b))
        from PIL import Image
        base = Image.open(a).convert("RGB")
        m = Image.open(b).convert("RGB")
        base.paste(m, (offset.x(), offset.y()))
        base.save(BUILD / name)
        meta[name] = (offset.x(), offset.y(), offset.x() + m.width, offset.y() + m.height)

    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.clear_files()
    w.set_rules([])
    pump(1)
    w.grab().save(str(BUILD / "cap-empty.png"))

    w.add_paths([lib / "Messy names", lib / "Music"])
    pump(3, lambda: len(w.model.items) >= 10)
    pump(1)
    w.grab().save(str(BUILD / "cap-files.png"))
    with_menu(w, rules_menu(w, lambda c: None), QPoint(272, 115), "cap-addrule.png")
    w._sync_more_menu()
    with_menu(w, w.more_menu, QPoint(1050, 50), "cap-more.png")
    sort_btn = w.sort_menu.parent()
    with_menu(w, w.sort_menu, sort_btn.mapTo(w, QPoint(0, sort_btn.height())), "cap-sort.png")

    w.clear_files()
    w.add_paths([demo])
    pump(3, lambda: w.model.items)
    w.set_rules([TrimRule(separators_to_spaces=True), CaseRule(mode="smart_title")])
    pump(1.5)
    w.apply()
    pump(5, lambda: w.history.batches)
    pump(1)
    dlg = HistoryDialog(w)
    dlg.resize(820, 420)
    dlg.show()
    pump(0.8)
    dlg.grab().save(str(BUILD / "cap-history.png"))
    dlg.close()
    w.close()
    shutil.rmtree(demo, ignore_errors=True)
    return meta


# ---- 2. slides -------------------------------------------------------------------
def font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (("segoeuib.ttf",) if bold else ()) + ("segoeui.ttf",):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def background():
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([1100, -500, 2300, 500], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(Image.new("RGB", (W, H), INDIGO), img, glow)


def wrap(draw, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=fnt) <= width:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def title_slide(slide, version) -> "Image":
    from PIL import Image, ImageDraw
    img = background()
    logo = Image.open(ROOT / "assets/branding/png/logo-mark-256.png").convert("RGBA").resize((200, 200))
    img.paste(logo, (160, 250), logo)
    d = ImageDraw.Draw(img)
    big = font(110, True)
    d.text((160, 480), "Alex", font=big, fill=CYAN)
    d.text((160 + d.textlength("Alex", font=big), 480), "bed", font=big, fill=VIOLET)
    d.text((166, 610), "Bulk Rename Utility", font=font(64, True), fill=TEXT)
    d.text((168, 710), slide["title"], font=font(48), fill=DIM)
    footer = (f"Version {version}  ·  Free  ·  Portable  ·  Open source  ·  Windows"
              if slide["kind"] == "title" else "github.com/alexbedca/Alexbed-Bulk-Rename-Utility")
    d.text((168, 860), footer, font=font(34), fill=FAINT if slide["kind"] == "title" else CYAN)
    if slide["kind"] == "title":  # the app itself on the right
        from PIL import ImageFilter
        shot = Image.open(SHOTS / "main-window.png").convert("RGB")
        shot = shot.resize((int(shot.width * 0.62), int(shot.height * 0.62)), Image.LANCZOS)
        x, y = 1010, 300
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).rectangle([x + 12, y + 20, x + shot.width + 12, y + shot.height + 20], fill=170)
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img,
                              shadow.filter(ImageFilter.GaussianBlur(26)))
        img.paste(shot, (x, y))
        ImageDraw.Draw(img).rectangle([x, y, x + shot.width - 1, y + shot.height - 1], outline=(38, 43, 77), width=2)
    return img


def step_slide(slide, n, total, meta) -> "Image":
    from PIL import Image, ImageDraw, ImageFilter
    img = background()
    d = ImageDraw.Draw(img)
    d.text((96, 44), f"STEP {n} OF {total}", font=font(26, True), fill=CYAN)
    d.text((96, 80), slide["title"], font=font(58, True), fill=TEXT)

    src = SHOTS / slide["image"] if (SHOTS / slide["image"]).exists() else BUILD / slide["image"]
    shot = Image.open(src).convert("RGB")
    boxes = [meta[slide["image"]] if b == "menu" else b for b in slide.get("boxes", [])]
    if boxes:  # dim everything except the highlighted areas
        mask = Image.new("L", shot.size, 0)
        md = ImageDraw.Draw(mask)
        for b in boxes:
            md.rounded_rectangle(b, radius=10, fill=255)
        dim = Image.blend(shot, Image.new("RGB", shot.size, (0, 0, 0)), 0.55)
        shot = Image.composite(shot, dim, mask)
    box_w, box_h = 1560, 780
    scale = min(box_w / shot.width, box_h / shot.height, 1.6)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
    x, y = (W - shot.width) // 2, 172 + (box_h - shot.height) // 2
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rectangle([x + 12, y + 20, x + shot.width + 12, y + shot.height + 20], fill=170)
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shadow.filter(ImageFilter.GaussianBlur(26)))
    img.paste(shot, (x, y))
    d = ImageDraw.Draw(img)
    d.rectangle([x, y, x + shot.width - 1, y + shot.height - 1], outline=(38, 43, 77), width=2)
    for b in boxes:
        bx = [x + b[0] * scale, y + b[1] * scale, x + b[2] * scale, y + b[3] * scale]
        d.rounded_rectangle([bx[0] - 4, bx[1] - 4, bx[2] + 4, bx[3] + 4], radius=12, outline=CYAN, width=5)

    cap_font = font(38)
    lines = wrap(d, slide["caption"], cap_font, 1700)
    top = 975 - 26 * (len(lines) - 1)
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=cap_font)
        d.text(((W - tw) / 2, top + i * 50), line, font=cap_font, fill=TEXT)
    return img


# ---- 3. narration, 4. video -------------------------------------------------------
def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> None:
    from alexed_bru import APP_VERSION
    BUILD.mkdir(parents=True, exist_ok=True)
    print("capturing screens…")
    meta = capture()
    (BUILD / "meta.json").write_text(json.dumps(meta))

    total = sum(1 for s in SLIDES if s.get("kind") is None)
    n = 0
    segments, cues, clock = [], [], 0.0
    lead, tail, fade = 0.6, 0.9, 0.35
    for i, slide in enumerate(SLIDES):
        if slide.get("kind"):
            img = title_slide(slide, APP_VERSION)
        else:
            n += 1
            img = step_slide(slide, n, total, meta)
        png = BUILD / f"slide{i:02d}.png"
        img.save(png)

        wav = BUILD / f"say{i:02d}.wav"
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "tools" / "tts.ps1"),
             "-Text", slide["say"], "-Out", str(wav), "-Voice", VOICE])
        speech = duration(wav)
        seg_len = lead + speech + tail
        # subtitles: split the narration into sentences, timed by length
        sentences = [s for s in re.split(r"(?<=[.!?:])\s+", slide["say"]) if s]
        chars = sum(len(s) for s in sentences)
        t = clock + lead
        for s in sentences:
            d = speech * len(s) / chars
            cues.append((t, t + d, s.replace("Reg Ex", "RegEx").replace("dot E X E", ".exe")))
            t += d

        seg = BUILD / f"seg{i:02d}.mp4"
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{seg_len:.3f}", "-i", str(png),
             "-i", str(wav),
             "-filter_complex",
             f"[0:v]format=yuv420p,fade=t=in:st=0:d={fade},fade=t=out:st={seg_len - fade:.3f}:d={fade}[v];"
             f"[1:a]adelay={int(lead * 1000)}|{int(lead * 1000)},apad,atrim=0:{seg_len:.3f},"
             f"aformat=sample_rates=48000:channel_layouts=stereo[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-tune", "stillimage", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", str(seg)])
        segments.append(seg)
        clock += seg_len
        print(f"slide {i + 1}/{len(SLIDES)}: {seg_len:.1f}s")

    listing = BUILD / "segments.txt"
    listing.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments))
    srt = OUT / "Alexbed-Bulk-Rename-Utility-how-to.srt"
    srt.write_text("\n".join(f"{k + 1}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
                             for k, (a, b, text) in enumerate(cues)), encoding="utf-8")
    final = OUT / "Alexbed-Bulk-Rename-Utility-how-to.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(srt),
         "-map", "0:v", "-map", "0:a", "-map", "1:s", "-c:v", "copy", "-c:s", "mov_text",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "160k",  # YouTube-level loudness
         "-metadata:s:s:0", "language=eng", "-metadata", f"title=Alexbed Bulk Rename Utility {APP_VERSION}: how to use it",
         "-movflags", "+faststart", str(final)])
    print(f"done: {final} ({duration(final):.1f}s, {final.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
