#!/usr/bin/env python3
"""Company names: placeholder checks, the verified mapping in data/company-sources.csv, and a step
that moves apps filed without a company into the right folder.

Every company name is the developer name on the app's store listing. When the source record has no
developer, the name comes from data/company-sources.csv, which keeps the primary source for each
row (the iTunes Lookup API `artistName` or the Google Play listing's developer). Names are never
guessed: an app with neither is left out of the export.

  python3 scripts/companies.py --apply   move apps filed under an unknown company to their resolved
                                         company, and drop the ones that can't be resolved
Standard library only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stacklib import dump_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "company-sources.csv"
UNKNOWN_SLUG = "_unknown"
COMPANY_SOURCE = "store_listing_developer"
PLACEHOLDER_RE = re.compile(r"^\W*(unknown(\s+(company|developer|seller))?|n/?a|tbd|tba|none|null|nil|undefined|-+|\?+)?\W*$", re.I)


def is_placeholder(name) -> bool:
    """True for a missing, blank or placeholder company name ('Unknown', 'N/A', 'TBD', ...)."""
    return name is None or not isinstance(name, str) or bool(PLACEHOLDER_RE.fullmatch(name.strip()))


def company_slug(name: str) -> str:
    """A folder-safe slug. Names with no Latin letters (e.g. Chinese company names) get a stable
    hash-based slug instead of falling back to an unknown bucket."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "company-" + hashlib.sha1(name.strip().encode()).hexdigest()[:10]


@lru_cache(maxsize=1)
def mapping() -> dict[tuple[str, str], dict]:
    if not SOURCES.exists():
        return {}
    with open(SOURCES, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        if is_placeholder(r["company"]) or not r["source_url"].strip() or not r["source_field"].strip():
            raise SystemExit(f"{SOURCES.name}: row for {r['platform']}/{r['store_id']} has no company or no source")
        out[(r["platform"], r["store_id"])] = r
    return out


def resolve(platform: str, store_id: str) -> dict | None:
    """The verified company for an app from data/company-sources.csv, as the doc's `company` object."""
    r = mapping().get((platform, store_id))
    if not r:
        return None
    return {"name": r["company"], "slug": r["company_slug"], "source": COMPANY_SOURCE, "unknown": False}


def bad_companies(docs) -> list[str]:
    """Files whose company is unknown, blank or a placeholder. The build fails on any of these."""
    bad = []
    for doc, path in docs:
        c = doc["app"]["company"]
        if c.get("unknown") or c.get("slug") == UNKNOWN_SLUG or is_placeholder(c.get("name")):
            bad.append(str(path))
    return bad


def apply(root: Path = ROOT, dry_run: bool = False) -> dict:
    """Moves every app under apps/<platform>/_unknown/ to its resolved company folder (rewriting the
    company in each version file) and removes the apps that can't be resolved."""
    moved, dropped = [], []
    for app_dir in sorted((root / "apps").glob(f"*/{UNKNOWN_SLUG}/*")):
        files = sorted(p for p in app_dir.glob("*.json") if p.name != "latest.json")
        if not files:
            continue
        first = json.loads(files[0].read_text())
        platform, sid = first["app"]["platform"], first["app"]["store_id"]
        comp = resolve(platform, sid)
        if comp is None:
            dropped.append(f"{platform}/{sid} ({first['app']['name']})")
            if not dry_run:
                shutil.rmtree(app_dir)
            continue
        dest = root / "apps" / platform / comp["slug"] / app_dir.name
        if dest.exists():
            dest = dest.with_name(f"{app_dir.name}-{re.sub(r'[^a-z0-9]+', '-', sid.lower())}")
        moved.append(f"{platform}/{sid} -> {comp['slug']}/{dest.name}")
        if dry_run:
            continue
        dest.mkdir(parents=True, exist_ok=False)
        for f in app_dir.iterdir():
            if f.suffix == ".json" and f.name != "latest.json":
                d = json.loads(f.read_text())
                d["app"]["company"] = dict(comp)
                d["app"]["slug"] = dest.name
                (dest / f.name).write_text(dump_json(d))
        shutil.rmtree(app_dir)
    for d in (root / "apps").glob(f"*/{UNKNOWN_SLUG}"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return {"moved": moved, "dropped": dropped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("use --apply or --dry-run")
    res = apply(dry_run=args.dry_run)
    print(f"moved: {len(res['moved'])}, left out (no verified company): {len(res['dropped'])}")
    for x in res["dropped"]:
        print(f"  left out: {x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
