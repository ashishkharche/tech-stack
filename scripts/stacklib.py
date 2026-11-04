"""Shared helpers for the Tech Stack exporter. Standard library only."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone

SCHEMA_VERSION = "1.1"

# Same rule as the source API's isPublicStoreVersion.
INTERNAL_VERSION_RE = re.compile(r"testflight|nightly|internal|alpha|beta|debug|adhoc|dogfood|canary|staging", re.I)
APPLE_ID_RE = re.compile(r"^\d{6,12}$")
ANDROID_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

# Base URL of the source API the exporter reads from (STACK_API_BASE). Only used for API calls; never written
# to the export.
SOURCE_BASE = os.environ.get("STACK_API_BASE", "").strip().rstrip("/")


def is_public_store_version(version: str | None) -> bool:
    value = (version or "").strip()
    return bool(value) and not INTERNAL_VERSION_RE.search(value)


def is_plausible_store_id(store: str, app_id: str) -> bool:
    if store == "apple":
        return bool(APPLE_ID_RE.match(app_id))
    if store == "google":
        return bool(ANDROID_PACKAGE_RE.match(app_id))
    return False


def compare_versions(a: str, b: str) -> int:
    """Port of the source API's compareAppVersions."""
    sa = [p for p in re.split(r"[.\-_+]", a) if p]
    sb = [p for p in re.split(r"[.\-_+]", b) if p]
    for i in range(max(len(sa), len(sb))):
        ai = sa[i] if i < len(sa) else "0"
        bi = sb[i] if i < len(sb) else "0"
        an, bn = re.fullmatch(r"-?\d+", ai), re.fullmatch(r"-?\d+", bi)
        if an and bn:
            if int(ai) != int(bi):
                return -1 if int(ai) < int(bi) else 1
        elif ai != bi:
            return -1 if ai < bi else 1
    return 0


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "_unknown"


def version_filename(version: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", version.strip()) + ".json"


def iso_utc(value: str | None) -> str | None:
    """Normalise SQLite / ISO timestamps to YYYY-MM-DDTHH:MM:SSZ (UTC). Unparseable values pass through."""
    if not value:
        return None
    v = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v + "T00:00:00Z"
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return v
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
