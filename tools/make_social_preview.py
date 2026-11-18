# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build docs/social-preview.png (1280x640), the GitHub repository card.

Run from the project folder after refreshing docs/screenshots/main-window.png:
    .venv\\Scripts\\python tools\\make_social_preview.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from alexed_bru import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 640
BG, CYAN, VIOLET, INDIGO = (11, 13, 26), (34, 211, 238), (192, 132, 252), (99, 102, 241)
TEXT, DIM, FAINT = (226, 232, 240), (170, 178, 204), (138, 147, 181)


def font(name: str, size: int):
    for n in (name, "segoeui.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
glow = Image.new("L", (W, H), 0)
ImageDraw.Draw(glow).ellipse([640, -320, 1500, 420], fill=95)
glow = glow.filter(ImageFilter.GaussianBlur(130))
img = Image.composite(Image.new("RGB", (W, H), INDIGO), img, glow)

logo = Image.open(ROOT / "assets/branding/png/logo-mark-256.png").convert("RGBA").resize((112, 112), Image.LANCZOS)
img.paste(logo, (70, 88), logo)
d = ImageDraw.Draw(img)
title = font("segoeuib.ttf", 68)
d.text((70, 226), "Alex", font=title, fill=CYAN)
d.text((70 + d.textlength("Alex", font=title), 226), "ed", font=title, fill=VIOLET)
d.text((72, 306), "Bulk Rename Utility", font=font("segoeuib.ttf", 40), fill=TEXT)
body = font("segoeui.ttf", 27)
d.text((72, 384), "Rename thousands of files safely:", font=body, fill=DIM)
d.text((72, 420), "live preview, no RegEx needed,", font=body, fill=DIM)
d.text((72, 456), "undo any batch.", font=body, fill=DIM)
d.text((72, 540), f"v{APP_VERSION} · Free · Portable · Open source · Windows", font=font("segoeui.ttf", 21),
       fill=FAINT)

shot = Image.open(ROOT / "docs/screenshots/main-window.png").convert("RGB")
shot = shot.resize((int(shot.width * 0.5), int(shot.height * 0.5)), Image.LANCZOS)
x, y = 560, 120
shadow = Image.new("L", (W, H), 0)
ImageDraw.Draw(shadow).rectangle([x + 10, y + 18, x + shot.width + 10, y + shot.height + 18], fill=170)
shadow = shadow.filter(ImageFilter.GaussianBlur(24))
img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shadow)
img.paste(shot, (x, y))
ImageDraw.Draw(img).rectangle([x, y, x + shot.width - 1, y + shot.height - 1], outline=(38, 43, 77), width=2)

out = ROOT / "docs/social-preview.png"
img.save(out)
print("saved", out, img.size)
