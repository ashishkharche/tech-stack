"""Tiny SVG chart and brand helpers for the generated README. Standard library only.

Every chart is written twice, once per GitHub theme (light / dark), and picked with
<picture> + prefers-color-scheme in the markdown. Text uses the system UI font stack."""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

NS = "http://www.w3.org/2000/svg"
# Brand type: Geist for labels and UI text (400 / 500), Geist Serif for display text. Viewers without
# Geist fall back to the system UI font. The brand is monochrome: no colour accent.
FONT = "Geist, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
SERIF = "'Geist Serif', Georgia, 'Times New Roman', serif"

# Layout problems found while drawing (text on text, text cut by a bar, text outside the canvas).
# build_readme.py fails the build when this is not empty.
ISSUES: list[str] = []

# The website palette (its colour tokens), monochrome: the accent is the text colour. Charts, text,
# cards and the logo use only these. The one exception is platform data: wherever iOS and Android
# values are shown, they use the platform colours below.
#
# iOS: Apple system blue, from the Human Interface Guidelines "Color" page (system colours table):
# Blue, light R0 G136 B255, dark R0 G145 B255.
# Android: the Android robot green #3DDC84, from the Android brand guidelines (Android Developers,
# Distribute > Marketing tools > Brand guidelines). The source gives one
# value. It is used as is on dark cards; on light cards it is only 1.7:1, so the light theme uses
# #1EA45A, the same hue and saturation darkened to the first step that reaches 3:1 (derived here,
# not an official value).
# Contrast (WCAG) of the bars on the chart card: iOS 3.3:1 light / 6.0:1 dark; Android 3.0:1 light /
# 10.9:1 dark. Between the two: 1.1:1 light / 1.8:1 dark, so the two are told apart by hue, and
# stacked segments are also split by a 2px gap and named in the legend.
PLATFORM_COLORS = {
    "light": {"ios": "#0088FF", "android": "#1EA45A"},
    "dark": {"ios": "#0091FF", "android": "#3DDC84"},
}
MID = "#5F6A6C"  # the site's diagram-edge grey: second step of the monochrome ramp
THEMES = {
    "light": {"bg": "#FAF8F3", "ink": "#090A0B", "muted": "#4D5755", "faint": "#D9E1DD",
              "soft": "#EEF2F0", "panel": "#E8EEEB", "s1": "#090A0B", "s2": MID, **PLATFORM_COLORS["light"]},
    "dark": {"bg": "#0C0D0E", "ink": "#F1F6F3", "muted": "#A9B2BC", "faint": "#262A2D",
             "soft": "#16191B", "panel": "#1B1F21", "s1": "#F1F6F3", "s2": MID, **PLATFORM_COLORS["dark"]},
}


def series_colors(t: dict, series) -> list[str]:
    """Series named iOS... or Android... take the platform colour. Other series are monochrome: the
    text colour, then the mid tone."""
    mono = iter([t["s1"], t["s2"]] * len(series))
    out = []
    for s in series:
        name = str(s).lower()
        out.append(t["ios"] if name.startswith("ios") else t["android"] if name.startswith("android") else next(mono))
    return out


PAD = 20      # inner margin of a chart card
RADIUS = 12   # corner radius of chart cards


def x(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def text_width(s: str, size: float) -> float:
    """Rough width of UI-font text, good enough for layout."""
    w = 0.0
    for ch in str(s):
        if ch in "il.,:;|!'1 ":
            w += 0.30
        elif ch in "mwMW@":
            w += 0.86
        elif ch.isupper() or ch.isdigit():
            w += 0.64
        else:
            w += 0.54
    return w * size


def fmt(n) -> str:
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


_ATTR = re.compile(r'([a-z-]+)="([^"]*)"')


def _boxes(body):
    texts, rects = [], []
    for el in body:
        tag = el[1:el.find(" ")] if el.startswith("<") else ""
        if tag not in ("text", "rect"):
            continue
        a = dict(_ATTR.findall(el[: el.find(">")]))
        try:
            if tag == "rect":
                if a.get("width", "").endswith("%"):
                    continue
                rects.append((float(a.get("x", 0)), float(a.get("y", 0)),
                              float(a.get("x", 0)) + float(a["width"]), float(a.get("y", 0)) + float(a["height"])))
            else:
                if "transform" in a:
                    continue
                content = re.sub(r"<[^>]+>", "", el[el.find(">") + 1:])
                content = content.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                size = float(a.get("font-size", 12))
                w = text_width(content, size) * (1.06 if a.get("font-weight") in ("500", "600", "700") else 1.0)
                x0 = float(a["x"])
                anchor = a.get("text-anchor", "start")
                x0 = x0 - w if anchor == "end" else x0 - w / 2 if anchor == "middle" else x0
                y = float(a["y"])
                texts.append((x0, y - 0.74 * size, x0 + w, y + 0.2 * size, content))
        except (KeyError, ValueError):
            continue
    return texts, rects


def _hit(a, b, pad=0.5):
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def _inside(t, r):
    return t[0] >= r[0] - 1 and t[2] <= r[2] + 1 and t[1] >= r[1] - 2 and t[3] <= r[3] + 2


def check_layout(width, height, body, label):
    texts, rects = _boxes(body)
    out = []
    for i, t in enumerate(texts):
        if t[0] < -0.5 or t[2] > width + 0.5 or t[1] < -0.5 or t[3] > height + 0.5:
            out.append(f"{label}: text '{t[4]}' runs outside the canvas")
        for u in texts[i + 1:]:
            if _hit(t, u):
                out.append(f"{label}: text '{t[4]}' overlaps '{u[4]}'")
        for r in rects:
            if _hit(t, r) and not _inside(t, r):
                out.append(f"{label}: text '{t[4]}' is cut by a shape")
    return out


def svg(width: float, height: float, body: list[str], bg: str | None = None, label: str = "",
        theme: str | None = None) -> str:
    """With a theme, the chart sits on a solid card in that theme's background (rounded, with a hairline
    border), so it reads the same whatever page colour is behind it."""
    ISSUES.extend(check_layout(width, height, body, label or "chart"))
    pad = PAD if theme else 0
    W, H = width + 2 * pad, height + 2 * pad
    head = (f'<svg xmlns="{NS}" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
            f'role="img" aria-label="{x(label)}" font-family="{x(FONT)}">')
    parts = [head]
    if label:
        parts.append(f"<title>{x(label)}</title>")
    if theme:
        t = THEMES[theme]
        parts.append(f'<rect x="0.5" y="0.5" width="{W - 1:.0f}" height="{H - 1:.0f}" rx="{RADIUS}" '
                     f'fill="{t["bg"]}" stroke="{t["faint"]}"/>')
        parts.append(f'<g transform="translate({pad} {pad})">')
    elif bg and bg != "none":
        parts.append(f'<rect width="100%" height="100%" rx="{RADIUS}" fill="{bg}"/>')
    parts += body
    if theme:
        parts.append("</g>")
    parts.append("</svg>\n")
    return "\n".join(parts)


# ---------------------------------------------------------------- brand

# Iso Block: an isometric box seen from above, its open front showing the stacked layers inside
# (odd layers knocked out). Drawn on a 512-unit grid; one flat colour, pure black or pure white.
ISO_BLOCK = (
    "M256.00 46.19 L53.04 163.37 L152.17 220.61 L253.65 162.02 L256.00 166.08 L258.35 162.02 L359.83 220.61 L458.96 163.37Z",
    "M48.35 405.86 L147.48 463.10 L147.48 228.74 L48.35 171.50Z",
    "M463.65 405.86 L463.65 171.50 L364.52 228.74 L364.52 463.10Z",
    "M156.86 407.35 L156.86 458.90 L251.31 404.37 L251.31 352.82Z",
    "M355.14 458.90 L355.14 407.35 L260.69 352.82 L260.69 404.37Z",
    "M251.31 284.48 L251.31 232.93 L156.86 287.46 L156.86 339.01Z",
    "M260.69 232.93 L260.69 284.48 L355.14 339.01 L355.14 287.46Z",
)
LOGO_INK = {"light": "#000000", "dark": "#FFFFFF"}
_NUM = re.compile(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)")


def logo_paths(size: float = 48, ox: float = 0, oy: float = 0) -> str:
    """The Iso Block mark as one path, scaled from its 512 grid to `size` and moved to (ox, oy)."""
    k = size / 512
    return " ".join(_NUM.sub(lambda m: f"{ox + float(m.group(1)) * k:.2f} {oy + float(m.group(2)) * k:.2f}", d)
                    for d in ISO_BLOCK)


def logo_svg(theme: str = "light", size: int = 512) -> str:
    """Pure black mark for light backgrounds, pure white for dark ones. Transparent background."""
    return (f'<svg xmlns="{NS}" viewBox="0 0 512 512" width="{size}" height="{size}" role="img" aria-label="Tech Stack logo">'
            f'<title>Tech Stack logo</title>'
            + "".join(f'<path fill="{LOGO_INK[theme]}" d="{d}"/>' for d in ISO_BLOCK) + "</svg>\n")


def badge_svg(label: str, theme: str = "light", filled: bool = True, platform: str | None = None) -> str:
    """A pill label. Filled: text colour with background-colour text. Outlined: border and muted text.
    Platform badges are filled with the platform colour and carry near-black text (5.6:1 or more)."""
    t = THEMES[theme]
    size = 12
    w = text_width(label, size) + 18
    h = 22
    fill, stroke, color = (t["ink"], "none", t["bg"]) if filled else (t["bg"], t["faint"], t["muted"])
    if platform:
        fill, stroke, color = t[platform], "none", "#090A0B"
    return svg(w, h, [
        f'<rect x="0.5" y="0.5" width="{w - 1:.1f}" height="{h - 1}" rx="{(h - 1) / 2}" fill="{fill}" stroke="{stroke}"/>',
        f'<text x="{w / 2:.1f}" y="15" font-size="{size}" font-weight="500" text-anchor="middle" fill="{color}">{x(label)}</text>',
    ], label=label)


# ---------------------------------------------------------------- charts

def legend(t, items, x0, y0):
    out, cx = [], x0
    for name, color in items:
        out.append(f'<rect x="{cx}" y="{y0 - 10}" width="12" height="12" rx="3" fill="{color}"/>')
        out.append(f'<text x="{cx + 18}" y="{y0}" font-size="13" fill="{t["muted"]}">{x(name)}</text>')
        cx += 18 + text_width(name, 13) + 22
    return out


def hbar(rows, theme, series=("iOS", "Android"), width=820, label="", value_suffix="", max_value=None,
         bar_h=18, gap=10, show_legend=True):
    """rows: [(label, [v_series1, v_series2, ...]), ...] drawn as stacked horizontal bars."""
    t = THEMES[theme]
    colors = series_colors(t, series)
    lw = max([text_width(r[0], 13) for r in rows] + [40]) + 16
    vw = 70
    top = 34 if show_legend and len(series) > 1 else 10
    H = top + len(rows) * (bar_h + gap) + 6
    mx = max_value or max([sum(r[1]) for r in rows] + [1])
    plot = width - lw - vw
    body = []
    if show_legend and len(series) > 1:
        body += legend(t, list(zip(series, colors)), lw, 18)
    for i, (name, vals) in enumerate(rows):
        y = top + i * (bar_h + gap)
        body.append(f'<text x="{lw - 12}" y="{y + bar_h - 4}" font-size="13" text-anchor="end" fill="{t["ink"]}">{x(name)}</text>')
        cx, drawn = lw, False
        for v, c in zip(vals, colors):
            w = plot * v / mx
            if w > 0:
                # a 2px gap in the background colour separates stacked segments
                gap_l = 2 if drawn and w > 3 else 0
                body.append(f'<rect x="{cx + gap_l:.1f}" y="{y}" width="{max(w - gap_l, 1.5):.1f}" height="{bar_h}" rx="3" fill="{c}"/>')
                drawn = True
            cx += w
        total = sum(vals)
        body.append(f'<text x="{cx + 8:.1f}" y="{y + bar_h - 4}" font-size="13" fill="{t["muted"]}">{fmt(total)}{value_suffix}</text>')
    return svg(width, H, body, label=label, theme=theme)


def split_bars(rows, theme, series=("iOS", "Android"), width=820, label=""):
    """rows: [(label, a, b)] each a 100% bar split between two series, with both values shown."""
    t = THEMES[theme]
    lw = max([text_width(r[0], 13) for r in rows] + [40]) + 16
    top, bar_h, gap = 34, 26, 16
    H = top + len(rows) * (bar_h + gap)
    plot = width - lw - 10
    c1, c2 = series_colors(t, series)
    body = legend(t, [(series[0], c1), (series[1], c2)], lw, 18)
    for i, (name, a, b) in enumerate(rows):
        y = top + i * (bar_h + gap)
        tot = (a + b) or 1
        wa = plot * a / tot
        body.append(f'<text x="{lw - 12}" y="{y + 18}" font-size="13" text-anchor="end" fill="{t["ink"]}">{x(name)}</text>')
        body.append(f'<rect x="{lw}" y="{y}" width="{wa:.1f}" height="{bar_h}" rx="4" fill="{c1}"/>')
        body.append(f'<rect x="{lw + wa + 2:.1f}" y="{y}" width="{max(plot - wa - 2, 0):.1f}" height="{bar_h}" rx="4" fill="{c2}"/>')
        body.append(f'<text x="{lw + 10}" y="{y + 18}" font-size="13" font-weight="500" fill="{t["bg"]}">{fmt(a)}</text>')
        body.append(f'<text x="{lw + plot - 10:.1f}" y="{y + 18}" font-size="13" font-weight="500" text-anchor="end" fill="{t["bg"]}">{fmt(b)}</text>')
    return svg(width, H, body, label=label, theme=theme)


def columns(cols, theme, series=("iOS", "Android"), width=820, height=240, label="", rotate=False, grouped=False):
    """cols: [(label, [values per series])] as stacked (or, with grouped, side-by-side) vertical columns."""
    t = THEMES[theme]
    colors = series_colors(t, series)
    top = (30 if len(series) > 1 else 0) + 24  # legend row, then headroom for value labels
    bottom = 56 if rotate else 30
    left, right = 10, 10
    plot_h = height - top - bottom
    n = max(len(cols), 1)
    slot = (width - left - right) / n
    bw = min(slot * 0.62, 46)
    mx = max([(max(v) if grouped else sum(v)) for _, v in cols] + [1])
    body = []
    if len(series) > 1:
        body += legend(t, list(zip(series, colors)), left, 18)
    base = top + plot_h
    body.append(f'<line x1="{left}" y1="{base + 0.5}" x2="{width - right}" y2="{base + 0.5}" stroke="{t["faint"]}"/>')
    for i, (name, vals) in enumerate(cols):
        cx = left + slot * i + (slot - bw) / 2
        y = base
        if grouped:
            sub = bw / len(vals)
            for j, (v, c) in enumerate(zip(vals, colors)):
                hh = plot_h * v / mx
                bx = cx + j * sub
                if v:
                    body.append(f'<rect x="{bx + 1:.1f}" y="{base - hh:.1f}" width="{sub - 2:.1f}" height="{max(hh, 1.5):.1f}" rx="2" fill="{c}"/>')
                    body.append(f'<text x="{bx + sub / 2:.1f}" y="{base - hh - 5:.1f}" font-size="11" text-anchor="middle" fill="{t["muted"]}">{fmt(v)}</text>')
            body.append(f'<text x="{cx + bw / 2:.1f}" y="{base + 18:.1f}" font-size="12" text-anchor="middle" fill="{t["ink"]}">{x(name)}</text>')
            continue
        drawn = False
        for v, c in zip(vals, colors):
            h = plot_h * v / mx
            if h > 0:
                y -= h
                gap = 2 if drawn and h > 3 else 0  # background-colour gap between stacked segments
                body.append(f'<rect x="{cx:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(h - gap, 1.5):.1f}" rx="2" fill="{c}"/>')
                drawn = True
        tot = sum(vals)
        if tot:
            body.append(f'<text x="{cx + bw / 2:.1f}" y="{y - 6:.1f}" font-size="12" text-anchor="middle" fill="{t["muted"]}">{fmt(tot)}</text>')
        lx, ly = cx + bw / 2, base + 18
        if rotate:
            body.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" text-anchor="end" transform="rotate(-40 {lx:.1f} {ly:.1f})" fill="{t["ink"]}">{x(name)}</text>')
        else:
            body.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" text-anchor="middle" fill="{t["ink"]}">{x(name)}</text>')
    return svg(width, height, body, label=label, theme=theme)


def diverging(rows, theme, left_name="Removed", right_name="Added", width=820, label=""):
    """rows: [(label, removed, added)] with removed drawn left of a centre line."""
    t = THEMES[theme]
    lw = max([text_width(r[0], 13) for r in rows] + [40]) + 16
    top, bar_h, gap = 34, 16, 9
    H = top + len(rows) * (bar_h + gap) + 4
    half = (width - lw - 20) / 2
    mid = lw + half
    mx = max([max(r[1], r[2]) for r in rows] + [1])
    body = legend(t, [(left_name, t["s2"]), (right_name, t["s1"])], lw, 18)
    body.append(f'<line x1="{mid:.1f}" y1="{top - 4}" x2="{mid:.1f}" y2="{H - 4}" stroke="{t["faint"]}"/>')
    for i, (name, rem, add) in enumerate(rows):
        y = top + i * (bar_h + gap)
        body.append(f'<text x="{lw - 12}" y="{y + bar_h - 3}" font-size="13" text-anchor="end" fill="{t["ink"]}">{x(name)}</text>')
        if rem:
            w = (half - 30) * rem / mx
            body.append(f'<rect x="{mid - w:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3" fill="{t["s2"]}"/>')
            body.append(f'<text x="{mid - w - 6:.1f}" y="{y + bar_h - 3}" font-size="12" text-anchor="end" fill="{t["muted"]}">{rem}</text>')
        if add:
            w = (half - 30) * add / mx
            body.append(f'<rect x="{mid:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3" fill="{t["s1"]}"/>')
            body.append(f'<text x="{mid + w + 6:.1f}" y="{y + bar_h - 3}" font-size="12" fill="{t["muted"]}">{add}</text>')
    return svg(width, H, body, label=label, theme=theme)


def spark_rows(rows, theme, width=820, label=""):
    """rows: [(label, [(version, value), ...])] one small line per app across its versions."""
    t = THEMES[theme]
    lw = max([text_width(r[0], 13) for r in rows] + [40]) + 16
    rh, top = 46, 10
    H = top + len(rows) * rh
    vw = 150
    plot = width - lw - vw
    body = []
    for i, (name, pts) in enumerate(rows):
        y0 = top + i * rh
        vals = [v for _, v in pts]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        n = len(pts)
        coords = []
        for j, (_, v) in enumerate(pts):
            px = lw + (plot * j / (n - 1) if n > 1 else plot / 2)
            py = y0 + 32 - 24 * (v - lo) / span
            coords.append((px, py))
        body.append(f'<text x="{lw - 12}" y="{y0 + 24}" font-size="13" text-anchor="end" fill="{t["ink"]}">{x(name)}</text>')
        body.append(f'<line x1="{lw}" y1="{y0 + 40.5}" x2="{lw + plot}" y2="{y0 + 40.5}" stroke="{t["faint"]}"/>')
        body.append('<polyline fill="none" stroke-width="2" stroke-linejoin="round" stroke="{}" points="{}"/>'.format(
            t["s1"], " ".join(f"{a:.1f},{b:.1f}" for a, b in coords)))
        for a, b in coords:
            body.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.6" fill="{t["s1"]}"/>')
        first, last = pts[0], pts[-1]
        body.append(f'<text x="{lw + plot + 14:.1f}" y="{y0 + 24}" font-size="13" fill="{t["muted"]}">'
                    f'{fmt(first[1])} → {fmt(last[1])} SDKs</text>')
        body.append(f'<text x="{lw + plot + 14:.1f}" y="{y0 + 40}" font-size="11" fill="{t["muted"]}">{n} versions</text>')
    return svg(width, H, body, label=label, theme=theme)


def paired_hbar(rows, theme, series=("iOS", "Android"), width=820, label=""):
    """rows: [(label, a, b)] two thin bars per row, one per series."""
    t = THEMES[theme]
    lw = max([text_width(r[0], 13) for r in rows] + [40]) + 16
    top, bh, inner, gap = 34, 9, 3, 12
    rh = 2 * bh + inner
    H = top + len(rows) * (rh + gap)
    vw = 50
    plot = width - lw - vw
    mx = max([max(r[1], r[2]) for r in rows] + [1])
    c1, c2 = series_colors(t, series)
    body = legend(t, [(series[0], c1), (series[1], c2)], lw, 18)
    for i, (name, a, b) in enumerate(rows):
        y = top + i * (rh + gap)
        body.append(f'<text x="{lw - 12}" y="{y + rh - 5}" font-size="13" text-anchor="end" fill="{t["ink"]}">{x(name)}</text>')
        for j, (v, c) in enumerate(((a, c1), (b, c2))):
            yy = y + j * (bh + inner)
            w = plot * v / mx
            body.append(f'<rect x="{lw}" y="{yy}" width="{max(w, 1.5):.1f}" height="{bh}" rx="2" fill="{c}"/>')
            body.append(f'<text x="{lw + w + 6:.1f}" y="{yy + bh - 0.5}" font-size="11" fill="{t["muted"]}">{fmt(v)}</text>')
    return svg(width, H, body, label=label, theme=theme)
