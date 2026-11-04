#!/usr/bin/env python3
"""Draws the README banner (assets/banner-light|dark .svg and .png).

Branding follows Ashish Kharche's website: monochrome (the accent is the text colour), the site's background,
text and muted colours, and Geist type. The lockup is the Iso Block mark followed by TECH STACK in
wide-spaced capitals (Geist Medium) on one line, and below it the tagline in Geist Serif. The text is converted to outlines, so the banner looks the same for every viewer.

Needs rsvg-convert (librsvg) and a folder with Geist-Medium.ttf and
GeistSerif-Regular.ttf, from the `geist` npm package 1.9 (SIL Open Font License). The package ships Geist
Serif only as .woff2, which librsvg does not render; convert it to .ttf first, e.g. with fontTools:
`f = TTFont("GeistSerif-Regular.woff2"); f.flavor = None; f.save("GeistSerif-Regular.ttf")`. The fonts
are only used for rendering and are not stored in this repo. The banner holds no numbers, so it
only needs redrawing when the design changes; the daily run does not touch it.

    python3 scripts/make_banner.py --font-dir /path/to/geist/fonts
    python3 scripts/make_banner.py --font-dir ... --logo new-logo.svg

The mark is read from an SVG file (default assets/logo/logo-light.svg, written by build_readme.py) and
filled with the banner's text colour, so a new logo can be swapped in without touching this script.
Any square SVG with a viewBox works.
"""
from __future__ import annotations

import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svgkit as K  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 640
WORDMARK = "TECH STACK"
TAGLINE = "How Great Apps Are Built"
# Website palette (light / dark): background and text.
BG = {"light": "#FAF8F3", "dark": "#0C0D0E"}
INK = {"light": "#090A0B", "dark": "#F1F6F3"}

MARK = 96            # mark size
GAP = 22             # space between the mark box and the wordmark
WORD_SIZE = 44       # wordmark, Geist 500
WORD_TRACK = 0.24    # letter spacing in em (wide-spaced capitals)
TAG_SIZE = 76        # tagline, Geist Serif 400
FONT_FILES = ("Geist-Medium.ttf",)
SERIF_NAMES = ("GeistSerif-Regular.ttf", "GeistSerif-Regular.otf")


def nested_logo(path: Path, x: float, y: float, size: float, fill: str) -> str:
    """Places a logo SVG file at (x, y) as a nested <svg>, keeping its viewBox, recoloured to `fill`."""
    text = path.read_text()
    m = re.search(r"<svg\b([^>]*)>(.*)</svg>", text, re.S)
    if not m:
        raise SystemExit(f"{path}: not an SVG")
    vb = re.search(r'viewBox="([^"]+)"', m.group(1))
    inner = re.sub(r"<title>.*?</title>", "", m.group(2), flags=re.S)
    inner = re.sub(r'fill="#[0-9A-Fa-f]{3,8}"', f'fill="{fill}"', inner)
    return (f'<svg x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" viewBox="{vb.group(1) if vb else "0 0 48 48"}">'
            f"{inner}</svg>")


def word_text(x: float, y: float, fill: str) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="Geist" font-weight="500" font-size="{WORD_SIZE}" '
            f'letter-spacing="{WORD_SIZE * WORD_TRACK:.2f}" fill="{fill}">{K.x(WORDMARK)}</text>')


def png_ink_columns(path: Path) -> tuple[int, int]:
    """First and last column with any ink in an 8-bit RGBA PNG (as written by rsvg-convert)."""
    data = path.read_bytes()
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            if depth != 8 or ctype != 6:
                raise SystemExit("unexpected PNG format while measuring the wordmark")
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + n
    raw, bpp, stride = zlib.decompress(idat), 4, width * 4
    prev, cols = bytearray(stride), set()
    for row in range(height):
        f = raw[row * (stride + 1)]
        line = bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        cols.update(i // 4 for i in range(3, stride, 4) if line[i] > 8)
        prev = line
    return min(cols), max(cols)


def source_svg(theme: str, logo: Path, word_ink: tuple[float, float]) -> str:
    cx = W / 2
    ink_x0, ink_x1 = word_ink                 # wordmark ink extent when set at x=0
    inset = MARK * 48.35 / 512                # the Iso Block's side margin inside its 512 box
    lock_w = MARK - inset + GAP + (ink_x1 - ink_x0)
    lx = (W - lock_w) / 2 - inset             # centre the inked lockup, not the mark's box
    # two rows, lockup then tagline; the inked block is centred on the canvas
    lock_top = 207
    word_base = lock_top + MARK / 2 + WORD_SIZE * 0.36   # cap height ~0.72em, centred on the mark
    tag_base = lock_top + MARK + 52 + TAG_SIZE * 0.72
    body = [
        f'<rect width="{W}" height="{H}" fill="{BG[theme]}"/>',
        nested_logo(logo, lx, lock_top, MARK, INK[theme]),
        word_text(lx + MARK + GAP - ink_x0, word_base, INK[theme]),
        f'<text x="{cx}" y="{tag_base:.1f}" font-family="Geist Serif" font-weight="400" font-size="{TAG_SIZE}" '
        f'text-anchor="middle" fill="{INK[theme]}">{K.x(TAGLINE)}</text>',
    ]
    return f'<svg xmlns="{K.NS}" width="{W}" height="{H}" viewBox="0 0 {W} {H}">' + "".join(body) + "</svg>\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--font-dir", required=True, help="folder with Geist-Medium.ttf and GeistSerif-Regular.ttf")
    ap.add_argument("--logo", type=Path, default=ROOT / "assets" / "logo" / "logo-light.svg",
                    help="logo SVG (recoloured to the text colour of each banner)")
    args = ap.parse_args()
    exe = shutil.which("rsvg-convert")
    fonts = Path(args.font_dir).resolve()
    serif = next((fonts / n for n in SERIF_NAMES if (fonts / n).exists()), None)
    if not exe or serif is None or not all((fonts / n).exists() for n in FONT_FILES):
        print("needs rsvg-convert and Geist-Medium.ttf and GeistSerif-Regular.ttf in --font-dir", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        only = tmp / "fonts"
        only.mkdir()
        for f in [fonts / n for n in FONT_FILES] + [serif]:
            shutil.copy(f, only / f.name)
        conf = tmp / "fonts.conf"
        conf.write_text(f'<?xml version="1.0"?><fontconfig><dir>{only}</dir><cachedir>{tmp / "cache"}</cachedir></fontconfig>')
        # Force the fontconfig backend so only the Geist files above are used (macOS pango otherwise uses CoreText).
        env = {"FONTCONFIG_FILE": str(conf), "PANGOCAIRO_BACKEND": "fc", "PATH": "/usr/bin:/bin"}
        # Measure the wordmark once (set at x=0) so the one-line lockup can be centred exactly.
        probe = tmp / "probe.svg"
        probe.write_text(f'<svg xmlns="{K.NS}" width="{W}" height="120" viewBox="0 0 {W} 120">'
                         + word_text(0, 80, "#000") + "</svg>")
        subprocess.run([exe, "-w", str(W), str(probe), "-o", str(tmp / "probe.png")], check=True, env=env)
        word_ink = png_ink_columns(tmp / "probe.png")
        word_ink = (word_ink[0], word_ink[1] + 1)
        for theme in ("light", "dark"):
            src = tmp / f"{theme}.svg"
            src.write_text(source_svg(theme, args.logo, word_ink))
            out_svg = ROOT / "assets" / f"banner-{theme}.svg"
            out_png = ROOT / "assets" / f"banner-{theme}.png"
            # cairo writes text as glyph outlines, so the SVG no longer depends on installed fonts
            subprocess.run([exe, "-f", "svg", str(src), "-o", str(out_svg)], check=True, env=env)
            subprocess.run([exe, "-w", str(W * 2), str(src), "-o", str(out_png)], check=True, env=env)
            if "<text" in out_svg.read_text():
                print(f"{out_svg.name}: text was not outlined", file=sys.stderr)
                return 1
            print(f"wrote {out_svg.relative_to(ROOT)} and {out_png.relative_to(ROOT)} ({W}x{H}, PNG at 2x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
