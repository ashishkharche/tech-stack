"""Turns one source tech-stack row into the public per-version JSON document (schema 1.1).

This is an ALLOWLIST: only the fields written below are exported. Everything else in the source
payload (backend hosts, GraphQL operations, pinned certificates, Firebase projects, SDK config
keys, API endpoints / base URLs, mined hosts, on-device data, SQL schemas, feature flags,
Android signers and secret counts, tracking domains, console fields, ...) is dropped.
"""
from __future__ import annotations

import re

from leakscan import unsafe_text
from companies import company_slug, is_placeholder, resolve as resolve_company
from stacklib import SCHEMA_VERSION, iso_utc, slugify

COMPANY_SOURCE = "store_listing_developer"
INFERRED_NOTE = "Written by a language model from the analysis; treat as unverified."

OBSERVED = {"present", "exact", "high", "medium"}
INFERRED = {"inferred", "mined", "low"}

# Insight themes built mostly from surfaces we never export (hosts, pinning, GraphQL, Firebase
# projects). Dropped whole rather than trusting a text filter.
DROP_THEMES = {"backend", "security"}
DROP_TOPICS_RE = re.compile(
    r"graphql|pinn|certificate|firebase project|project id|storage bucket|database url|secret|api key|config key"
    r"|endpoint|base url|\bhosts?\b|hostname|domain|\bsql|schema|signer|signing|on-device data|feature flag|\burl",
    re.I,
)


def _strs(value) -> list[str]:
    return [str(x) for x in (value or []) if isinstance(x, (str, int, float)) and str(x).strip()]


def _banned_values(payload: dict) -> set[str]:
    """Raw values of never-export fields, used to make sure model-written text doesn't echo them."""
    out: set[str] = set()

    def add(v):
        if isinstance(v, str) and len(v.strip()) >= 6:
            out.add(v.strip().lower())
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, list):
            for x in v:
                add(x)

    services = payload.get("services") or {}
    backend = payload.get("backend") or {}
    android = payload.get("android") or {}
    for v in (
        services.get("firebaseProjects"), services.get("sdkConfigKeys"), backend.get("hosts"),
        backend.get("graphqlOperations"), backend.get("pinnedCertificates"), payload.get("onDeviceData"),
        payload.get("sqlSchemas"), payload.get("featureFlags"), (payload.get("stringMining") or {}).get("extraHosts"),
        android.get("apiEndpoints"), android.get("baseUrls"), android.get("signers"),
        (payload.get("privacy") or {}).get("trackingDomains"),
    ):
        add(v)
    return out


def sdk_confidence(item: dict) -> str:
    c = (item.get("confidence") or "").lower()
    if c in OBSERVED:
        return "observed"
    if c in INFERRED:
        return "inferred"
    return "unknown"


def _sdks(payload: dict) -> list[dict]:
    out, seen = [], set()
    for group in payload.get("sdks") or []:
        for item in group.get("items") or []:
            name = str(item.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            ver = item.get("version")
            out.append({
                "name": name,
                "version": str(ver) if ver not in (None, "") else None,
                "category": str(item.get("category") or group.get("category") or "other"),
                "confidence": sdk_confidence(item),
            })
    return out


def _platform(payload: dict, platform: str, min_os_fallback: str | None) -> dict:
    p = payload.get("platform") or {}
    a = payload.get("android") or {}
    if platform == "ios":
        return {
            "min_os": (p.get("minIos") or min_os_fallback or None),
            "min_sdk": None,
            "target_sdk": None,
            "build_sdk": p.get("sdk") or None,
            "xcode": p.get("xcode") or None,
            "device_families": _strs(p.get("deviceFamilies")),
            "abis": [],
            "localization_count": p.get("languageCount") if isinstance(p.get("languageCount"), int) else None,
        }
    min_sdk = str(a.get("minSdk") or "") or None
    return {
        "min_os": (f"Android API {min_sdk}" if min_sdk else (min_os_fallback or None)),
        "min_sdk": min_sdk,
        "target_sdk": str(a.get("targetSdk") or "") or None,
        "build_sdk": None,
        "xcode": None,
        "device_families": _strs(p.get("deviceFamilies")) or ["Android"],
        "abis": _strs(a.get("abis")),
        "localization_count": None,
    }


def _privacy(payload: dict, platform: str) -> dict:
    pr = payload.get("privacy") or {}
    a = payload.get("android") or {}
    return {
        "declares_tracking": bool(pr.get("declaresTracking")),
        "tracking_domain_count": len(pr.get("trackingDomains") or []),
        "collected_data_types": _strs(pr.get("collectedDataTypes")),
        "required_reason_apis": _strs(pr.get("requiredReasonApis")),
        "android_permissions": sorted(set(_strs(a.get("permissions")))) if platform == "android" else [],
    }


def _inferred(payload: dict) -> tuple[list[dict], int]:
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        return [], 0
    banned = _banned_values(payload)
    dropped = 0
    insights = []
    for ins in analysis.get("insights") or []:
        theme = str(ins.get("theme") or "")
        title = str(ins.get("title") or "")
        detail = str(ins.get("detail") or "")
        text = f"{title}\n{detail}"
        if theme in DROP_THEMES or DROP_TOPICS_RE.search(text) or unsafe_text(text, banned):
            dropped += 1
            continue
        insights.append({"theme": theme, "title": title, "detail": detail})
    headline = str(analysis.get("headline") or "")
    if headline and (DROP_TOPICS_RE.search(headline) or unsafe_text(headline, banned)):
        headline = None
        dropped += 1
    if not headline and not insights:
        return [], dropped
    return [{
        "kind": "analysis",
        "method": "model_written_summary_of_detected_signals",
        "note": INFERRED_NOTE,
        "generated_at": iso_utc(analysis.get("generatedAt")),
        "headline": headline or None,
        "insights": insights,
    }], dropped


def build_doc(rec: dict) -> tuple[dict, dict]:
    """rec keys: app_id, store, version, captured_at, sdk_count, sdk_list_is_floor, binary_encrypted,
    stale (bool|None), payload, app {name, slug, active, developer, developer_slug, bundle_id},
    vinfo {first_seen_at, store_updated_at, min_os} | None, paths {company_slug, app_slug} | None.
    Returns (doc, stats)."""
    payload = rec["payload"] or {}
    store = rec["store"]
    platform = "ios" if store == "apple" else "android"
    app = rec["app"]
    dev = (app.get("developer") or "").strip()
    # The developer name from the store listing; a placeholder ("Unknown", "N/A", ...) counts as none.
    # Without one, the verified mapping in data/company-sources.csv is used. With neither, the company
    # stays unknown and export.py leaves the app out.
    if dev and not is_placeholder(dev):
        company = {"name": dev, "slug": app.get("developer_slug") or company_slug(dev),
                   "source": COMPANY_SOURCE, "unknown": False}
    else:
        company = resolve_company(platform, rec["app_id"]) or {"name": None, "slug": "_unknown", "source": None, "unknown": True}
    if rec.get("paths") and not (rec["paths"].get("company") or {}).get("unknown"):
        # Once an app is exported its company (and folder) stays put across runs and sources.
        company = dict(rec["paths"].get("company") or company, slug=rec["paths"]["company_slug"])
        if company.get("source"):
            company["source"] = COMPANY_SOURCE
    # A name checked against the live store listing (data/company-sources.csv) always wins, so a
    # differently spelled source name or an earlier mapping can't come back on the next export.
    verified = resolve_company(platform, rec["app_id"])
    if verified:
        company = verified
    app_slug = (rec.get("paths") or {}).get("app_slug") or app.get("slug") or payload.get("slug") or slugify(app.get("name") or rec["app_id"])
    version = rec["version"]
    vinfo = rec.get("vinfo") or {}
    conf = payload.get("confidence") or {}
    inferred, dropped = _inferred(payload)
    bundle_id = app.get("bundle_id") or payload.get("bundleId") or (rec["app_id"] if platform == "android" else None)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "app": {
            "name": app.get("name") or payload.get("appName") or rec["app_id"],
            "slug": app_slug,
            "platform": platform,
            "store": "app_store" if store == "apple" else "google_play",
            "store_id": rec["app_id"],
            "bundle_id": bundle_id or None,
            "active": bool(app.get("active")),
            "company": company,
        },
        "version": version,
        "public_store_build": True,
        "dates": {
            "captured_at": iso_utc(rec["captured_at"]),
            "store_first_seen_at": iso_utc(vinfo.get("first_seen_at")),
            "store_updated_at": iso_utc(vinfo.get("store_updated_at")),
            "exported_at": None,
        },
        "source": {
            "kind": "static_binary_analysis",
            "artifact": "ipa" if platform == "ios" else "apk",
            "tool": "static-analyzer",
        },
        "confidence": {
            "sdk_list_is_floor": bool(rec["sdk_list_is_floor"]),
            "binary_encrypted": bool(rec["binary_encrypted"]),
            "packed": bool(conf.get("packed")),
            "packers": _strs(conf.get("packers")),
            "stale": rec.get("stale"),
        },
        "stack": {
            "sdk_count": int(rec.get("sdk_count") or 0),
            "languages": _strs(payload.get("languages")),
            "frameworks": _strs(payload.get("appleFrameworks")),
            "ui_graphics": _strs(payload.get("uiGraphics")),
            "build_system": _strs(payload.get("buildSystem")),
            "sdks": _sdks(payload),
            "platform": _platform(payload, platform, vinfo.get("min_os")),
            "capabilities": _strs(payload.get("capabilities")),
            "privacy": _privacy(payload, platform),
        },
        "inferred": inferred,
    }
    return doc, {"insights_dropped": dropped}


def upgrade_doc(doc: dict) -> bool:
    """Brings an older version document up to the current schema in place. Returns True if it changed.

    1.0 -> 1.1: source URLs dropped, company.source renamed, inferred[] note reworded."""
    if doc.get("schema_version") == SCHEMA_VERSION:
        return False
    doc["schema_version"] = SCHEMA_VERSION
    src = doc.get("source") or {}
    doc["source"] = {k: src[k] for k in ("kind", "artifact", "tool") if k in src}
    comp = doc["app"]["company"]
    if comp.get("source"):
        comp["source"] = COMPANY_SOURCE
    for item in doc.get("inferred") or []:
        item["note"] = INFERRED_NOTE
    return True
