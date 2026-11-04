#!/usr/bin/env python3
"""Cross-file consistency and README stats check. Standard library only.

Checks that index.csv, sdks.csv, latest.json copies, companies/ and the README headline numbers all
agree with the version files under apps/. Exits 1 on any error; warnings are printed but do not fail.
Run: python3 scripts/check_consistency.py"""
from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def main() -> int:
    files = sorted(p for p in (ROOT / "apps").glob("*/*/*/*.json") if p.name != "latest.json")
    docs = {p.relative_to(ROOT).as_posix(): json.loads(p.read_text()) for p in files}
    index = list(csv.DictReader((ROOT / "index.csv").open()))
    by_path = {r["path"]: r for r in index}

    # index.csv <-> version files
    for p in sorted(set(docs) - set(by_path)):
        err(f"index.csv: no row for {p}")
    for p in sorted(set(by_path) - set(docs)):
        err(f"index.csv: row points at missing file {p}")
    if len(by_path) != len(index):
        err("index.csv: duplicate path rows")
    for p, d in docs.items():
        r = by_path.get(p)
        if not r:
            continue
        a = d["app"]
        want = {
            "platform": a["platform"], "app": a["name"], "app_slug": a["slug"], "company": a["company"]["name"],
            "company_slug": a["company"]["slug"], "store_id": a["store_id"], "version": d["version"],
            "sdk_count": str(d["stack"]["sdk_count"]), "captured_at": d["dates"]["captured_at"],
            "active": str(a["active"]).lower(),
        }
        for k, v in want.items():
            if r.get(k) != v:
                err(f"index.csv {p}: {k}={r.get(k)!r}, file has {v!r}")
        parts = p.split("/")
        if parts[1] != a["platform"] or parts[2] != a["company"]["slug"] or parts[3] != a["slug"]:
            err(f"{p}: path does not match platform/company/app slug")
        n, listed = d["stack"]["sdk_count"], len(d["stack"]["sdks"])
        if n != listed:
            warn(f"{p}: sdk_count {n} but {listed} SDKs listed")
        if d["stack"]["sdk_count"] == 0:
            warn(f"{p}: 0 SDKs detected")
        if d["dates"].get("store_updated_at") and d["dates"]["store_updated_at"] > d["dates"]["exported_at"]:
            err(f"{p}: store_updated_at after exported_at")

    # one latest per app, latest.json identical to it
    apps = defaultdict(list)
    for r in index:
        apps[r["path"].rsplit("/", 1)[0]].append(r)
    latest = {}
    for app_dir, rows in apps.items():
        ls = [r for r in rows if r["is_latest"] == "true"]
        if len(ls) != 1:
            err(f"{app_dir}: {len(ls)} rows marked is_latest")
            continue
        latest[app_dir] = docs.get(ls[0]["path"])
        lj = ROOT / app_dir / "latest.json"
        if not lj.exists() or json.loads(lj.read_text()) != latest[app_dir]:
            err(f"{app_dir}/latest.json is not a copy of {ls[0]['path']}")
        if not (ROOT / app_dir / "README.md").exists():
            err(f"{app_dir}: README.md missing")
    sids = Counter((d["app"]["platform"], d["app"]["store_id"]) for d in latest.values() if d)
    for k, v in sids.items():
        if v > 1:
            err(f"store id {k} appears in {v} app folders")

    # sdks.csv: names are grouped case-insensitively, like generate.py
    expect = defaultdict(set)
    for app_dir, d in latest.items():
        for s in d["stack"]["sdks"] if d else []:
            expect[s["name"].lower()].add(app_dir[len("apps/"):])
    sdk_rows = list(csv.DictReader((ROOT / "sdks.csv").open()))
    seen = set()
    for r in sdk_rows:
        key = r["sdk"].lower()
        seen.add(key)
        got = set(filter(None, r["apps"].split(";")))
        if got != expect.get(key, set()):
            err(f"sdks.csv {r['sdk']}: app list differs from latest versions")
        if int(r["app_count"]) != len(got) or int(r["ios_apps"]) + int(r["android_apps"]) != len(got):
            err(f"sdks.csv {r['sdk']}: counts do not add up")
    for k in sorted(set(expect) - seen):
        err(f"sdks.csv: missing SDK {k}")

    # companies
    companies = defaultdict(set)
    for d in latest.values():
        if d:
            companies[d["app"]["company"]["slug"]].add(d["app"]["company"]["name"])
    pages = {p.stem for p in (ROOT / "companies").glob("*.md")} - {"README"}
    for s in sorted(set(companies) ^ pages):
        err(f"companies/: page/company mismatch for {s}")
    for s in companies:
        if re.fullmatch(r"company-[0-9a-f]{10}", s):
            err(f"company slug {s} is a hash; give it a readable slug in data/company-sources.csv")
    for s, names in companies.items():
        if len(names) > 1:
            warn(f"company {s} is spelled {len(names)} ways: {sorted(names)}")

    # README headline numbers
    readme = (ROOT / "README.md").read_text()
    vals = [d for d in latest.values() if d]
    ios = [d for d in vals if d["app"]["platform"] == "ios"]
    android = [d for d in vals if d["app"]["platform"] == "android"]
    m = re.search(r"([\d,]+) apps · ([\d,]+) versions · ([\d,]+) companies · ([\d,]+) SDKs", readme)
    if not m:
        err("README: headline stats line not found")
    else:
        got = [int(x.replace(",", "")) for x in m.groups()]
        want = [len(vals), len(docs), len(companies), len(sdk_rows)]
        for label, g, w in zip(("apps", "versions", "companies", "SDKs"), got, want):
            if g != w:
                err(f"README: says {g} {label}, data has {w}")
    def claim(pattern: str, want: tuple, label: str) -> None:
        mm = re.search(pattern, readme)
        if not mm:
            err(f"README: claim not found: {label}")
        elif tuple(mm.groups()) != tuple(str(x) for x in want):
            err(f"README: {label}: says {mm.groups()}, data gives {want}")
    fb = len(expect.get("firebase", ()))
    claim(r"Firebase is in (\d+) of (\d+) apps", (fb, len(vals)), "Firebase")
    claim(r"in (\d+) of (\d+) Android apps", (sum(any("Compose" in x for x in d["stack"]["frameworks"] + d["stack"].get("ui_graphics", [])) for d in android), len(android)), "Jetpack Compose")
    med = lambda xs: f"{statistics.median(xs):g}"  # noqa: E731
    claim(r"median app ships ([\d.]+) SDKs on iOS and ([\d.]+) on Android",
          (med([d["stack"]["sdk_count"] for d in ios]), med([d["stack"]["sdk_count"] for d in android])), "median SDKs")
    top = max(vals, key=lambda d: d["stack"]["sdk_count"])
    claim(r"has the most, at (\d+)", (top["stack"]["sdk_count"],), "largest SDK list")
    pct = round(100 * sum(any(s["category"] == "analytics" for s in d["stack"]["sdks"]) for d in vals) / len(vals))
    claim(r"(\d+)% of apps ship at least one analytics SDK", (pct,), "analytics share")
    per_co = Counter(d["app"]["company"]["slug"] for d in vals)
    claim(r"(?:has|share) the most apps, with (\d+)(?: each)?\. (\d+) of (\d+) companies have one app",
          (per_co.most_common(1)[0][1], sum(v == 1 for v in per_co.values()), len(per_co)), "apps per company")

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print(f"checked {len(docs)} versions, {len(latest)} apps, {len(sdk_rows)} SDK rows: "
          f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
