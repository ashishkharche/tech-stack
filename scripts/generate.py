"""Rebuilds every generated file from apps/<platform>/<company>/<app>/<version>.json.

latest.json, index.csv and sdks.csv are written here; README.md, the per-app READMEs, companies/,
the charts and the banner are written by build_readme.py, which this calls at the end."""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from functools import cmp_to_key
from pathlib import Path

from companies import apply as file_resolved_companies, bad_companies
from stacklib import compare_versions, dump_json, now_utc
from transform import upgrade_doc

INDEX_COLUMNS = [
    "platform", "company", "company_slug", "company_unknown", "app", "app_slug", "store", "store_id", "bundle_id",
    "version", "is_latest", "captured_at", "store_updated_at", "sdk_count", "active",
    "sdk_list_is_floor", "binary_encrypted", "packed", "stale", "has_inferred", "path",
]


def load_docs(root: Path):
    """Yields (doc, path) for every version file, upgrading older schema versions on disk first."""
    for path in sorted((root / "apps").glob("*/*/*/*.json")):
        if path.name == "latest.json":
            continue
        doc = json.loads(path.read_text())
        if upgrade_doc(doc):
            doc["dates"]["exported_at"] = now_utc()
            path.write_text(dump_json(doc))
        yield doc, path


def _write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def _md(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def _b(v) -> str:
    return "" if v is None else ("true" if v else "false")


def _csv(rows, header) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def regenerate(root: Path) -> dict:
    # Apps filed without a company move to their verified company (data/company-sources.csv); the
    # rest are left out. Then the build fails if any company is still unknown, blank or a placeholder.
    filed = file_resolved_companies(root)
    for x in filed["dropped"]:
        print(f"left out (no verified company): {x}")
    apps: dict[Path, list[tuple[dict, Path]]] = defaultdict(list)
    all_docs = list(load_docs(root))
    bad = bad_companies(all_docs)
    if bad:
        raise SystemExit(f"{len(bad)} version file(s) have an unknown or placeholder company, e.g. {bad[0]}")
    for doc, path in all_docs:
        apps[path.parent].append((doc, path))

    by_ver = cmp_to_key(lambda a, b: compare_versions(a[0]["version"], b[0]["version"])
                        or ((a[0]["dates"]["captured_at"] or "") > (b[0]["dates"]["captured_at"] or "")) - ((a[0]["dates"]["captured_at"] or "") < (b[0]["dates"]["captured_at"] or "")))
    index_rows, latest_docs = [], []
    companies: dict[str, dict] = {}
    for app_dir, docs in sorted(apps.items()):
        docs.sort(key=by_ver, reverse=True)
        latest, _ = docs[0]
        latest_docs.append((latest, app_dir))
        _write_if_changed(app_dir / "latest.json", dump_json(latest))
        a = latest["app"]
        rel = app_dir.relative_to(root)
        for d, p in docs:
            c = d["confidence"]
            index_rows.append([
                a["platform"], a["company"]["name"] or "", a["company"]["slug"], _b(a["company"]["unknown"]), a["name"], a["slug"],
                a["store"], a["store_id"], a["bundle_id"] or "", d["version"], _b(d is latest), d["dates"]["captured_at"] or "",
                d["dates"]["store_updated_at"] or "", d["stack"]["sdk_count"], _b(a["active"]),
                _b(c["sdk_list_is_floor"]), _b(c["binary_encrypted"]), _b(c["packed"]), _b(c.get("stale")),
                _b(bool(d.get("inferred"))), str(p.relative_to(root)),
            ])
        comp = companies.setdefault(a["company"]["slug"], {"name": a["company"]["name"], "unknown": a["company"]["unknown"],
                                                           "source": a["company"]["source"], "apps": []})
        comp["apps"].append((latest, len(docs), rel))

    _write_if_changed(root / "index.csv", _csv(index_rows, INDEX_COLUMNS))

    # SDK -> apps, from each app's latest version.
    sdk_apps: dict[str, dict] = {}
    for d, app_dir in latest_docs:
        a = d["app"]
        for s in d["stack"]["sdks"]:
            e = sdk_apps.setdefault(s["name"].lower(), {"name": s["name"], "categories": set(), "apps": [], "ios": 0, "android": 0, "observed": 0})
            e["categories"].add(s["category"])
            e["apps"].append(f"{a['platform']}/{a['company']['slug']}/{a['slug']}")
            e[a["platform"]] += 1
            e["observed"] += s["confidence"] == "observed"
    sdk_rows = sorted(sdk_apps.values(), key=lambda e: (-len(e["apps"]), e["name"].lower()))
    _write_if_changed(root / "sdks.csv", _csv(
        [[e["name"], ";".join(sorted(e["categories"])), len(e["apps"]), e["ios"], e["android"], e["observed"], ";".join(sorted(e["apps"]))] for e in sdk_rows],
        ["sdk", "categories", "app_count", "ios_apps", "android_apps", "observed_in", "apps"]))

    stats = {
        "apps": len(latest_docs),
        "apps_ios": sum(1 for d, _ in latest_docs if d["app"]["platform"] == "ios"),
        "apps_android": sum(1 for d, _ in latest_docs if d["app"]["platform"] == "android"),
        "versions": len(index_rows),
        "companies": len(companies),
        "sdks": len(sdk_rows),
        "inactive_apps": sum(1 for d, _ in latest_docs if not d["app"]["active"]),
        "versions_with_inferred": sum(1 for r in index_rows if r[-2] == "true"),
    }
    # README.md, app READMEs, companies/, charts, logo and banner.
    from build_readme import build  # noqa: PLC0415
    built = build(root)
    stats["icons"] = built["icons"]
    return stats
