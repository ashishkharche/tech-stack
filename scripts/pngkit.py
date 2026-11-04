"""Rounds app icons to one shape: a square with rounded corners and a transparent outside.

Store icons arrive in different shapes (App Store icons are plain squares, Google Play icons are often
already masked), so every cached PNG is given the same corner radius. The mask only ever lowers alpha,
so running it again on a rounded icon changes nothing. Reads 8-bit PNGs (grey, RGB, palette, grey +
alpha, RGBA; not interlaced) and writes RGBA. Standard library only."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

MAGIC = b"\x89PNG\r\n\x1a\n"
RADIUS = 0.225  # corner radius as a share of the icon's width
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunks(data: bytes):
    pos = 8
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + n]
        pos += 12 + n


def decode(data: bytes) -> tuple[int, int, list[bytearray]] | None:
    """Returns (width, height, RGBA rows), or None for a format this module does not read."""
    if not data.startswith(MAGIC):
        return None
    idat, plte, trns, hdr = b"", b"", b"", None
    for kind, chunk in _chunks(data):
        if kind == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            plte = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat += chunk
    if not hdr:
        return None
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or interlace or ctype not in CHANNELS:
        return None
    bpp = CHANNELS[ctype]
    stride = w * bpp
    raw = zlib.decompress(idat)
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        out = bytearray(w * 4)
        for x in range(w):
            if ctype == 6:
                out[x * 4:x * 4 + 4] = line[x * 4:x * 4 + 4]
            elif ctype == 2:
                out[x * 4:x * 4 + 4] = line[x * 3:x * 3 + 3] + b"\xff"
            elif ctype == 0:
                v = line[x]
                out[x * 4:x * 4 + 4] = bytes((v, v, v, 255))
            elif ctype == 4:
                v = line[x * 2]
                out[x * 4:x * 4 + 4] = bytes((v, v, v, line[x * 2 + 1]))
            else:
                k = line[x]
                alpha = trns[k] if k < len(trns) else 255
                out[x * 4:x * 4 + 4] = plte[k * 3:k * 3 + 3] + bytes((alpha,))
        rows.append(out)
    return w, h, rows


def encode(w: int, h: int, rows: list[bytearray]) -> bytes:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def mask(w: int, h: int) -> list[list[int]]:
    """Coverage (0-255) of a rounded square, 4x4 supersampled at the corners."""
    r = RADIUS * w
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            cx = r if x < r else w - r if x >= w - r else None
            cy = r if y < r else h - r if y >= h - r else None
            if cx is None or cy is None:
                row.append(255)
                continue
            hit = 0
            for sy in range(4):
                for sx in range(4):
                    dx, dy = x + (sx + 0.5) / 4 - cx, y + (sy + 0.5) / 4 - cy
                    hit += dx * dx + dy * dy <= r * r
            row.append(round(255 * hit / 16))
        out.append(row)
    return out


def round_icon(path: Path) -> bool:
    """Rounds the corners of a PNG icon in place. Returns True when the file changed."""
    data = path.read_bytes()
    img = decode(data)
    if img is None:
        return False
    w, h, rows = img
    m = mask(w, h)
    changed = False
    for y, row in enumerate(rows):
        for x, cov in enumerate(m[y]):
            if cov < 255 and row[x * 4 + 3] > cov:
                row[x * 4 + 3] = cov
                changed = True
    if not changed:
        return False
    path.write_bytes(encode(w, h, rows))
    return True
