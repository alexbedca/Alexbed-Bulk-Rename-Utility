# Copyright (C) 2026 Alexander Bediako
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rasterise the Alexbed Bulk Rename Utility logo mark to PNG + Windows .ico.

Pure Pillow (no Cairo needed). Mirrors the geometry of logo-mark.svg on a
512-unit grid, renders supersampled at 2048px, then downsamples.

Usage:  python export_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "png"
SS = 2048                  # supersample canvas
K = SS / 512               # grid -> pixels


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def gradient(size: int, stops: list[tuple[float, str]], direction: str) -> Image.Image:
    """Linear gradient. direction 'tl-br' (bg) or 'bl-tr' (accent)."""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    cols = [(p, hex_rgb(c)) for p, c in stops]
    for y in range(small):
        for x in range(small):
            u, v = x / (small - 1), y / (small - 1)
            t = (u + v) / 2 if direction == "tl-br" else (u + (1 - v)) / 2
            for (p0, c0), (p1, c1) in zip(cols, cols[1:]):
                if t <= p1:
                    px[x, y] = lerp(c0, c1, (t - p0) / (p1 - p0) if p1 > p0 else 0)
                    break
            else:
                px[x, y] = cols[-1][1]
    return img.resize((size, size), Image.BICUBIC)


def radial_glow(size: int) -> Image.Image:
    small = 256
    rgba = Image.new("RGBA", (small, small))
    px = rgba.load()
    r, g, b = hex_rgb("#6366F1")
    cx, cy, rad = 0.3, 0.15, 0.8
    for y in range(small):
        for x in range(small):
            d = (((x / small) - cx) ** 2 + ((y / small) - cy) ** 2) ** 0.5 / rad
            a = max(0.0, 1 - d) * 0.35
            px[x, y] = (r, g, b, round(a * 255))
    return rgba.resize((size, size), Image.BICUBIC)


def p(*xy: float) -> list[float]:
    return [v * K for v in xy]


def stroke_polyline(draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], width: float, fill) -> None:
    """Polyline with round caps and round joins."""
    w = width * K
    scaled = [(x * K, y * K) for x, y in pts]
    draw.line(scaled, fill=fill, width=round(w), joint="curve")
    r = w / 2
    for x, y in scaled:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def render_mark() -> Image.Image:
    canvas = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))

    # Tile
    tile_mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle([0, 0, SS - 1, SS - 1], radius=112 * K, fill=255)
    bg = gradient(SS, [(0, "#1E2344"), (1, "#0A0C18")], "tl-br").convert("RGBA")
    bg.alpha_composite(radial_glow(SS))
    canvas.paste(bg, (0, 0), tile_mask)

    overlay = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle(p(4, 4, 508, 508), radius=108 * K, outline=(255, 255, 255, 20), width=round(2 * K))

    # Ghost file rows
    for y, w, a in ((108, 96, 0.10), (142, 64, 0.07), (176, 40, 0.05)):
        d.rounded_rectangle(p(84, y, 84 + w, y + 18), radius=9 * K, fill=(255, 255, 255, round(a * 255)))
    canvas.alpha_composite(overlay)

    # "A" with gradient stroke
    a_mask = Image.new("L", (SS, SS), 0)
    stroke_polyline(ImageDraw.Draw(a_mask), [(130, 404), (236, 112), (342, 404)], 58, 255)
    accent = gradient(SS, [(0, "#22D3EE"), (0.5, "#6366F1"), (1, "#C084FC")], "bl-tr")
    canvas.paste(accent, (0, 0), a_mask)

    # Rename-arrow crossbar (knockout + white)
    d = ImageDraw.Draw(canvas, "RGBA")
    shaft = [(158, 306), (384, 306)]
    head = [(354, 266), (400, 306), (354, 346)]
    for width, colour in ((66, (18, 21, 42, 255)), (34, (255, 255, 255, 255))):
        stroke_polyline(d, shaft, width, colour)
        stroke_polyline(d, head, width, colour)

    # Re-clip to tile so nothing bleeds past the rounded corners
    canvas.putalpha(Image.composite(canvas.getchannel("A"), Image.new("L", (SS, SS), 0), tile_mask))
    return canvas


def main() -> None:
    OUT.mkdir(exist_ok=True)
    mark = render_mark()
    sizes = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
    for s in sizes:
        mark.resize((s, s), Image.LANCZOS).save(OUT / f"logo-mark-{s}.png", optimize=True)
    ico_sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    mark.resize((256, 256), Image.LANCZOS).save(HERE / "app.ico", sizes=ico_sizes)
    print(f"Wrote {len(sizes)} PNGs to {OUT} and app.ico")


if __name__ == "__main__":
    main()
