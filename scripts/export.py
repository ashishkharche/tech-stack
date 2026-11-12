#!/usr/bin/env python3
"""Export tech-stack data (public store builds only) from the source API into this repo.

Sources
  --source api   (default) keyed source API. Needs STACK_API_KEY in the environment. Incremental:
                 only versions not already in apps/ are fetched. Capped by --max-requests and
                 paced under 60 requests a minute so a free-tier key (60 rpm, 1,000 units/day,
                 1 unit per call) is never exceeded. Re-running continues where it stopped.
  --source raw   JSON files from a read-only SQLite query (stacks.json, apps.json, versions.json),
                 see scripts/README.md. Used for the initial export.

After fetching, every generated file (latest.json, per-app README, companies/, index.csv,
sdks.csv, README.md) is rebuilt from the per-version JSON files on disk.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import regenerate, load_docs  # noqa: E402
from stacklib import (SOURCE_BASE, compare_versions, dump_json, is_plausible_store_id,  # noqa: E402
                    is_public_store_version, now_utc, version_filename, INTERNAL_VERSION_RE)
from transform import build_doc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PRE_RELEASE_WORD_RE = re.compile(r"testflight|nightly|internal|alpha|beta|debug|adhoc|dogfood|canary|staging|preview|dev|qa", re.I)

# Public-site denylist (mirrors TDN src/lib/hidden-tech-stack.ts). These apps stay in the
# source database, but they must not appear in this catalogue. Keys are store:id in lower case,
# including iOS bundle ids.
HIDDEN_TECH_STACK_KEYS = {
    "apple:6670324846",  # Grok iOS
    "apple:ai.x.grokapp",
    "google:ai.x.grok",
    "apple:6794501026",  # Grok Bot iOS
    "apple:co.anysphere.sand",
    "google:ai.x.grok.bot",
    "apple:333903271",  # X iOS
    "apple:com.atebits.tweetie2",
    "google:com.twitter.android",
}


def is_hidden_tech_stack(store: str, app_id: str, bundle_id: str | None = None) -> bool:
    keys = [f"{store}:{app_id}".lower()]
    if bundle_id:
        keys.append(f"{store}:{bundle_id}".lower())
    return any(key in HIDDEN_TECH_STACK_KEYS for key in keys)


def excluded_app(store: str, app_id: str, bundle_id: str | None, name: str | None) -> str | None:
    """Apps that are not a public store listing (or are a pre-release channel) are left out."""
    if is_hidden_tech_stack(store, app_id, bundle_id):
        return "hidden_from_public_site"
    if not is_plausible_store_id(store, app_id):
        return "not_a_store_id"
    # A pre-release channel is its own store listing (e.g. "<App> Beta", "com.example.app.beta").
    # Match whole id segments / name words only, so "co.alphaexploration.clubhouse" is not caught.
    parts = re.split(r"[.\s_()-]+", f"{app_id} {bundle_id or ''} {name or ''}")
    if any(PRE_RELEASE_WORD_RE.fullmatch(p) for p in parts if p):
        return "pre_release_channel"
    return None


def existing_paths() -> dict[tuple[str, str], dict]:
    """(store, store_id) -> {company_slug, app_slug} so paths never move once exported."""
    out = {}
    for doc, path in load_docs(ROOT):
        a = doc["app"]
        store = "apple" if a["platform"] == "ios" else "google"
        out[(store, a["store_id"])] = {"company_slug": path.parts[-3], "app_slug": path.parts[-2], "company": a["company"]}
    return out


def write_doc(doc: dict) -> tuple[Path, bool]:
    a = doc["app"]
    d = ROOT / "apps" / a["platform"] / a["company"]["slug"] / a["slug"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / version_filename(doc["version"])
    if path.exists():
        old = json.loads(path.read_text())
        old_cmp = dict(old, dates=dict(old["dates"], exported_at=None))
        if old_cmp == doc:
            return path, False
    doc = dict(doc, dates=dict(doc["dates"], exported_at=now_utc()))
    path.write_text(dump_json(doc))
    return path, True


def unique_slugs(recs: list[dict], paths: dict) -> None:
    """Give each new app a slug that is unique within its platform/company folder."""
    taken = {(("ios" if s == "apple" else "android"), p["company_slug"], p["app_slug"]): sid for (s, sid), p in paths.items()}
    for r in recs:
        key = (r["store"], r["app_id"])
        if key in paths:
            r["paths"] = paths[key]
            continue
        doc, _ = build_doc(r)
        plat, comp, slug = doc["app"]["platform"], doc["app"]["company"]["slug"], doc["app"]["slug"]
        owner = taken.get((plat, comp, slug))
        if owner is not None and owner != r["app_id"]:
            slug = f"{slug}-{r['app_id'].replace('.', '-').lower()}"
        taken[(plat, comp, slug)] = r["app_id"]
        paths[key] = {"company_slug": comp, "app_slug": slug, "company": doc["app"]["company"]}
        r["paths"] = paths[key]


def apply(recs: list[dict]) -> dict:
    stats = {"written": 0, "unchanged": 0, "skipped_non_public_version": 0, "excluded_apps": {}, "insights_dropped": 0}
    paths = existing_paths()
    keep = []
    for r in recs:
        if not is_public_store_version(r["version"]):
            stats["skipped_non_public_version"] += 1
            continue
        why = excluded_app(r["store"], r["app_id"], r["app"].get("bundle_id"), r["app"].get("name"))
        if not why and build_doc(r)[0]["app"]["company"]["unknown"]:
            # No developer name from the source and none verified in data/company-sources.csv:
            # left out rather than filed under an unknown company.
            why = "no_verified_company"
        if why:
            stats["excluded_apps"].setdefault(why, set()).add((r["store"], r["app_id"]))
            continue
        keep.append(r)
    unique_slugs(keep, paths)
    for r in keep:
        doc, s = build_doc(r)
        stats["insights_dropped"] += s["insights_dropped"]
        _, changed = write_doc(doc)
        stats["written" if changed else "unchanged"] += 1
    stats["excluded_apps"] = {k: len(v) for k, v in stats["excluded_apps"].items()}
    return stats


# ---------------------------------------------------------------- raw (read-only SQLite dump)

def load_raw(raw_dir: Path) -> list[dict]:
    stacks = json.loads((raw_dir / "stacks.json").read_text())
    apps = {(a["app_id"], a["store"]): a for a in json.loads((raw_dir / "apps.json").read_text())}
    vers = {(v["app_id"], v["store"], v["version"]): v for v in json.loads((raw_dir / "versions.json").read_text())}
    recs = []
    for s in stacks:
        a = apps.get((s["app_id"], s["store"]))
        if a is None:
            continue
        payload = json.loads(s["payload"]) if isinstance(s["payload"], str) else s["payload"]
        recs.append({
            "app_id": s["app_id"], "store": s["store"], "version": s["version"], "captured_at": s["captured_at"],
            "sdk_count": s["sdk_count"], "sdk_list_is_floor": s["sdk_list_is_floor"], "binary_encrypted": s["binary_encrypted"],
            "stale": bool(s.get("stale")), "payload": payload,
            "app": {"name": a["name"], "slug": a["slug"], "active": a["active"], "developer": a["developer"],
                    "developer_slug": a["developer_slug"],
                    "bundle_id": (a.get("ios_bundle_id") or None) if s["store"] == "apple" else s["app_id"]},
            "vinfo": vers.get((s["app_id"], s["store"], s["version"])),
        })
    return recs


# ---------------------------------------------------------------- keyed API

class Budget(Exception):
    pass


class Api:
    def __init__(self, key: str, max_requests: int, min_interval: float):
        self.key, self.left, self.min_interval, self.last, self.calls = key, max_requests, min_interval, 0.0, 0

    def get(self, path: str, params: dict | None = None):
        if self.left <= 0:
            raise Budget("request budget for this run used up")
        url = f"{SOURCE_BASE}{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.left -= 1
            self.calls += 1
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json",
                                                       "User-Agent": "tech-stack-exporter"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    self._check_daily(resp.headers.get("RateLimit"))
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 429:
                    retry = int(e.headers.get("Retry-After") or "60")
                    if retry > 300:
                        raise Budget("daily quota reached")
                    time.sleep(retry + 1)
                    continue
                if e.code in (401, 403):
                    raise SystemExit(f"API refused the key (HTTP {e.code}). Check the STACK_API_KEY secret.")
                if e.code >= 500 and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        raise Budget("too many retries")

    @staticmethod
    def _check_daily(header: str | None):
        # RateLimit: "<minute remaining>;w=60, <daily remaining>;w=86400"
        if not header or "86400" not in header:
            return
        try:
            daily = int(header.split(",")[1].split(";")[0].strip())
        except (IndexError, ValueError):
            return
        if daily < 20:
            raise Budget("daily quota nearly used; stopping to leave headroom")


def _paged(api: Api, path: str, items_key: str | None):
    cursor = None
    while True:
        params = {"limit": 500}
        if cursor:
            params["cursor"] = cursor
        body = api.get(path, params) or {}
        if items_key:
            yield from body.get(items_key) or []
            cursor = body.get("nextCursor")
        else:
            yield from body.get("data") or []
            cursor = (body.get("meta") or {}).get("nextCursor")
        if not cursor:
            return


def load_api(api: Api, have: set[tuple[str, str, str]], refresh_meta: bool) -> tuple[list[dict], dict]:
    info = {"calls_listing": 0, "apps_checked": 0, "stopped_early": None}
    active = {(a["store"], a["id"]): a for a in _paged(api, "/api/v1/apps", "apps")}
    latest = list(_paged(api, "/api/v1/tech-stack", None))
    info["calls_listing"] = api.calls
    recs: list[dict] = []
    # Newest captures first so the freshest data lands even if the budget runs out.
    latest.sort(key=lambda x: x.get("capturedAt") or "", reverse=True)
    meta_by_app: dict[tuple[str, str], dict] = {}
    try:
        for row in latest:
            store, app_id = row["store"], row["appId"]
            if not is_public_store_version(row.get("version")):
                continue
            if excluded_app(store, app_id, row.get("bundleId"), row.get("appName")):
                continue
            listed = active.get((store, app_id))
            meta = {"name": (listed or {}).get("name") or row.get("appName"), "slug": row.get("slug"),
                    "active": listed is not None,
                    "developer": (listed or {}).get("developer") or row.get("developer") or "",
                    "developer_slug": (listed or {}).get("developerSlug") or row.get("developerSlug") or "", "bundle_id": row.get("bundleId") if store == "apple" else app_id}
            meta_by_app[(store, app_id)] = meta
            if (store, app_id, row["version"]) in have:
                continue
            info["apps_checked"] += 1
            detail = (api.get(f"/api/v1/tech-stack/{urllib.parse.quote(app_id)}", {"store": store}) or {}).get("data")
            if not detail:
                continue
            versions = [v["version"] for v in detail.get("versions") or [] if is_public_store_version(v.get("version"))]
            todo = [v for v in versions if (store, app_id, v) not in have]
            dates = {}
            vbody = api.get(f"/api/v1/apps/{urllib.parse.quote(app_id)}/versions", {"store": store, "limit": 200}) or {}
            for v in vbody.get("versions") or []:
                dates[v["version"]] = {"first_seen_at": v.get("firstSeenAt"), "store_updated_at": v.get("storeUpdatedAt"),
                                       "min_os": v.get("minOs")}
            for ver in todo:
                d = detail if ver == detail.get("version") else (
                    api.get(f"/api/v1/tech-stack/{urllib.parse.quote(app_id)}", {"store": store, "version": ver}) or {}).get("data")
                if not d or not is_public_store_version(d.get("version")):
                    continue
                recs.append({
                    "app_id": app_id, "store": store, "version": d["version"], "captured_at": d.get("capturedAt"),
                    "sdk_count": d.get("sdkCount"), "sdk_list_is_floor": d.get("sdkListIsFloor"),
                    "binary_encrypted": d.get("binaryEncrypted"), "stale": None, "payload": d.get("techStack") or {},
                    "app": meta, "vinfo": dates.get(d["version"]),
                })
    except Budget as b:
        info["stopped_early"] = str(b)
    info["meta_by_app"] = meta_by_app
    return recs, info


def refresh_app_meta(meta_by_app: dict) -> int:
    """Update active flag / company name on already-exported files without extra API calls."""
    changed = 0
    for doc, path in load_docs(ROOT):
        a = doc["app"]
        store = "apple" if a["platform"] == "ios" else "google"
        m = meta_by_app.get((store, a["store_id"]))
        if m is None:
            # Not in the public tech-stack list any more: leave the file, mark inactive only if the source says so.
            continue
        new_active = bool(m["active"])
        if a["active"] != new_active:
            a["active"] = new_active
            path.write_text(dump_json(doc))
            changed += 1
    return changed


def prune_hidden_apps() -> dict:
    """Remove denylisted apps from the latest tree (files, icons, empty company folders).

    Chart SVGs and company pages are dropped on the following regenerate. Git history is kept.
    """
    removed_dirs: list[str] = []
    removed_icons: list[str] = []
    seen: set[Path] = set()
    for doc, path in list(load_docs(ROOT)):
        a = doc["app"]
        store = "apple" if a["platform"] == "ios" else "google"
        if not is_hidden_tech_stack(store, a["store_id"], a.get("bundle_id")):
            continue
        app_dir = path.parent
        if app_dir in seen:
            continue
        seen.add(app_dir)
        if app_dir.exists():
            shutil.rmtree(app_dir)
            removed_dirs.append(str(app_dir.relative_to(ROOT)))
        plat = "ios" if store == "apple" else "android"
        icon = ROOT / "assets" / "icons" / plat / f"{a['store_id']}.png"
        if icon.exists():
            icon.unlink()
            removed_icons.append(str(icon.relative_to(ROOT)))
    for company_dir in (ROOT / "apps").glob("*/*"):
        if company_dir.is_dir() and not any(company_dir.iterdir()):
            company_dir.rmdir()
    return {"app_dirs": removed_dirs, "icons": removed_icons}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["api", "raw"], default="api")
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--max-requests", type=int, default=900, help="hard cap on API calls this run (default 900)")
    ap.add_argument("--min-interval", type=float, default=1.2, help="seconds between API calls (default 1.2 = 50/min)")
    ap.add_argument("--regenerate-only", action="store_true")
    args = ap.parse_args()

    summary: dict = {}
    summary["pruned_hidden"] = prune_hidden_apps()
    if not args.regenerate_only:
        if args.source == "raw":
            if not args.raw_dir:
                ap.error("--raw-dir is required with --source raw")
            recs = load_raw(args.raw_dir)
            summary.update(apply(recs))
        else:
            key = (os.environ.get("STACK_API_KEY") or "").strip()
            if not key or not SOURCE_BASE:
                print("STACK_API_BASE and STACK_API_KEY must both be set; nothing to do.", file=sys.stderr)
                return 2
            api = Api(key, args.max_requests, args.min_interval)
            have = set()
            for doc, _ in load_docs(ROOT):
                have.add(("apple" if doc["app"]["platform"] == "ios" else "google", doc["app"]["store_id"], doc["version"]))
            recs, info = load_api(api, have, refresh_meta=True)
            summary.update(apply(recs))
            summary["active_flags_changed"] = refresh_app_meta(info.pop("meta_by_app"))
            summary.update(info)
            summary["api_calls"] = api.calls
    summary["generated"] = regenerate(ROOT)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
