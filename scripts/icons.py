#!/usr/bin/env python3
"""Fetches small app icons from the public store listings and caches them in assets/icons/.

iOS: the iTunes Lookup API's artworkUrl512, requested at 128 px PNG. The GB storefront is tried
first, then the app's own storefronts (us, cn, jp, ...) when the GB lookup is empty.
Android: the Google Play listing page's og:image, requested at 128 px.

Each fetched icon's source (lookup or listing URL, the field, the artwork URL and the time) is kept
in data/icon-sources.csv. An icon counts as verified only when the file and its source row both
exist. Only icons that are missing are fetched, unless --refresh-all. Failures are recorded in
assets/icons/missing.json and retried after RETRY_DAYS, so a daily run does not hammer the stores.
Nothing is invented: an app without a verified icon is left out of the README, charts and lists
(build_readme.py flags it). PNG icons are given the same rounded corners (scripts/pngkit.py) so
every icon has one shape; `--round-all` applies that to the whole cache.
Standard library only."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pngkit import round_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "assets" / "icons"
MISSING = ICON_DIR / "missing.json"
SOURCES = ROOT / "data" / "icon-sources.csv"
SOURCE_COLUMNS = ["platform", "store_id", "source_url", "source_field", "artwork_url", "store_country", "fetched_at"]
RETRY_DAYS = 7
SIZE = 128
LOOKUP = "https://itunes.apple.com/lookup"
PLAY = "https://play.google.com/store/apps/details"
COUNTRIES = ["gb", "us", "cn", "jp", "kr", "tw", "hk", "in", "de", "fr", "sg", "br", "ru", "ca", "au"]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def icon_path(platform: str, store_id: str, ext: str | None = None) -> Path:
    """Cached icon path. Without ext, returns the existing .png or .jpg (or the .png path)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", store_id)
    base = ICON_DIR / platform / safe
    if ext:
        return base.with_name(f"{safe}.{ext}")
    for e in ("png", "jpg"):
        if base.with_name(f"{safe}.{e}").exists():
            return base.with_name(f"{safe}.{e}")
    return base.with_name(f"{safe}.png")


def load_sources() -> dict[tuple[str, str], dict]:
    if not SOURCES.exists():
        return {}
    with open(SOURCES, newline="") as fh:
        return {(r["platform"], r["store_id"]): r for r in csv.DictReader(fh)}


def save_sources(rows: dict[tuple[str, str], dict]) -> None:
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    with open(SOURCES, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SOURCE_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows[k] for k in sorted(rows))


def verified_icon(platform: str, store_id: str, sources: dict | None = None) -> Path | None:
    """The cached icon path when the file exists and its store source is on record, else None."""
    sources = load_sources() if sources is None else sources
    p = icon_path(platform, store_id)
    return p if p.exists() and (platform, store_id) in sources else None


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _save_icon(data: bytes, platform: str, store_id: str) -> bool:
    """Keeps the bytes as served (PNG or JPEG); anything else is treated as a failure."""
    if len(data) < 200:
        return False
    if data.startswith(PNG_MAGIC):
        ext = "png"
    elif data.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    else:
        return False
    path = icon_path(platform, store_id, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if ext == "png":
        round_icon(path)
    return True


def apps_from_data():
    seen = {}
    for f in sorted((ROOT / "apps").glob("*/*/*/*.json")):
        a = json.loads(f.read_text())["app"]
        seen[(a["platform"], a["store_id"])] = a["name"]
    return seen


def fetch_ios(ids: list[str], pause: float) -> dict[str, dict | None]:
    got: dict[str, dict | None] = {}
    todo = list(ids)
    for country in COUNTRIES:
        if not todo:
            break
        for i in range(0, len(todo), 100):
            batch = todo[i:i + 100]
            q = urllib.parse.urlencode({"id": ",".join(batch), "country": country, "entity": "software"})
            try:
                res = json.loads(_get(f"{LOOKUP}?{q}"))["results"]
            except Exception as e:  # noqa: BLE001
                print(f"  lookup {country} failed: {type(e).__name__}")
                continue
            time.sleep(pause)
            for r in res:
                sid = str(r.get("trackId", ""))
                art512 = r.get("artworkUrl512") or ""
                if sid not in batch or got.get(sid) or not art512:
                    continue
                art = re.sub(r"/\d+x\d+bb\.(jpg|png|webp)$", f"/{SIZE}x{SIZE}bb.png", art512)
                try:
                    ok = _save_icon(_get(art), "ios", sid)
                except Exception:  # noqa: BLE001
                    ok = False
                got[sid] = {"source_url": f"{LOOKUP}?id={sid}&country={country}", "source_field": "artworkUrl512",
                            "artwork_url": art512, "store_country": country} if ok else None
                time.sleep(pause)
        todo = [s for s in todo if not got.get(s)]
    return got


def fetch_android(pkg: str) -> dict | None:
    q = urllib.parse.urlencode({"id": pkg, "hl": "en", "gl": "US"})
    html = _get(f"{PLAY}?{q}").decode("utf-8", "replace")
    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if not m:
        return None
    base = re.sub(r"=[a-z0-9-]+$", "", m.group(1))
    if not _save_icon(_get(base + f"=s{SIZE}"), "android", pkg):
        return None
    return {"source_url": f"{PLAY}?{q}", "source_field": "og:image", "artwork_url": base, "store_country": "us"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=400, help="max icons to try this run")
    ap.add_argument("--pause", type=float, default=0.4, help="seconds between store requests")
    ap.add_argument("--retry-now", action="store_true", help="ignore the retry wait for earlier failures")
    ap.add_argument("--round-all", action="store_true", help="round the corners of every cached PNG icon and exit")
    ap.add_argument("--refresh-all", action="store_true",
                    help="fetch every app's icon again from its store listing and record its source")
    args = ap.parse_args()
    if args.round_all:
        pngs = sorted(ICON_DIR.glob("*/*.png"))
        changed = sum(round_icon(p) for p in pngs)
        others = sorted(x.name for x in ICON_DIR.glob("*/*.jpg"))
        print(f"rounded {changed} of {len(pngs)} PNG icons" + (f"; JPEG icons left as served: {len(others)}" if others else ""))
        return 0

    missing = json.loads(MISSING.read_text()) if MISSING.exists() else {}
    if args.retry_now:
        missing = {}
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=RETRY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    apps = apps_from_data()
    sources = load_sources()
    if args.refresh_all:
        missing = {}
        want = list(apps)[: args.max]
    else:
        want = [(p, s) for (p, s) in apps if not verified_icon(p, s, sources)
                and missing.get(f"{p}/{s}", "") < cutoff][: args.max]
    print(f"apps: {len(apps)}, verified icons: {sum(bool(verified_icon(p, s, sources)) for p, s in apps)}, to fetch: {len(want)}")

    results: dict[tuple[str, str], dict | None] = {}
    ios_ids = [s for p, s in want if p == "ios"]
    if ios_ids:
        got = fetch_ios(ios_ids, args.pause)
        for s in ios_ids:
            results[("ios", s)] = got.get(s)
    for p, s in want:
        if p != "android":
            continue
        try:
            results[(p, s)] = fetch_android(s)
        except Exception:  # noqa: BLE001
            results[(p, s)] = None
        time.sleep(args.pause)

    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for (p, s), src in results.items():
        key = f"{p}/{s}"
        if src:
            missing.pop(key, None)
            sources[(p, s)] = {"platform": p, "store_id": s, **src, "fetched_at": stamp}
        else:
            missing[key] = stamp
            if args.refresh_all:
                # The store no longer serves an icon for it: the old copy is no longer verified.
                sources.pop((p, s), None)
    sources = {k: v for k, v in sources.items() if k in apps}
    save_sources(sources)
    # Forget apps that left the data set.
    missing = {k: v for k, v in sorted(missing.items()) if tuple(k.split("/", 1)) in apps}
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    MISSING.write_text(json.dumps(missing, indent=2) + "\n")
    ok = sum(1 for v in results.values() if v)
    print(f"fetched: {ok}, failed: {len(results) - ok}, verified: {sum(bool(verified_icon(p, s, sources)) for p, s in apps)}")
    for (p, s), good in sorted(results.items()):
        if not good:
            print(f"  no icon: {p}/{s} ({apps[(p, s)]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
