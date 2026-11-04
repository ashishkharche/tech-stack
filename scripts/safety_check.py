#!/usr/bin/env python3
"""Pre-commit safety gate. Exits non-zero if the export contains anything it must not.

Export scope (must be 0 of everything): apps/, companies/, data/, index.csv, sdks.csv, README.md, docs/, schema/,
and the text files in assets/ (SVG logo, banner, charts, badges; the SVG namespace declaration is ignored).
  - versions (file names, JSON `version`, index.csv) matching the pre-release pattern
  - URLs whose host is not a store; hostnames; emails; key-like strings
  - the source's brand name (as a word or a domain), so the export only ever says Tech Stack
  - never-export field names anywhere in a JSON document
Tooling scope (scripts/, .github/) is scanned too and reported; the only allowed hits are the
ones listed in TOOLING_ALLOW (e.g. the repo's one commit identity).
Standard library only."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leakscan import DOTTED_RE, INTERNAL_WORD_RE, find_emails, find_hosts, find_keys, find_urls  # noqa: E402
from stacklib import is_public_store_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANNED_KEYS = {
    "secretCounts", "firebaseProjects", "sdkConfigKeys", "hosts", "graphqlOperations", "pinnedCertificates",
    "apiEndpoints", "baseUrls", "extraHosts", "stringMining", "onDeviceData", "sqlSchemas", "featureFlags",
    "signers", "visibility", "trackingDomains", "backend", "services", "inputHash", "model",
}
TOOLING_ALLOW = {"41898282+github-actions[bot]@users.noreply.github.com", "users.noreply.github.com", "user.email",
                 # Public store icon source used by scripts/icons.py (iTunes Lookup API).
                 "https://itunes.apple.com/lookup", "itunes.apple.com",
                 # SVG namespace declaration in scripts/svgkit.py (not a link).
                 "http://www.w3.org/2000/svg", "www.w3.org",
                 }
# The one commit identity allowed in this repo (scripts/check_commit_identity.sh, the workflows),
# the GitHub web-UI committer it names, and the checker's own file names.
TOOLING_ALLOW |= {"thekharche@gmail.com", "gmail.com", "noreply@github.com", "github.com",
                  "check_commit_identity.sh", "check.sh"}
# Store image host allowed in data/ (the icon sources), named below in this file.
TOOLING_ALLOW |= {"play-lh.googleusercontent.com"}
# Words that must never appear anywhere in the repo (for example the data source's own brand), as a word,
# an identifier prefix or a domain. Set them in STACK_BLOCKED_TERMS (comma separated) or one per line in
# the gitignored file .blocked-terms. Letters right before a term do not count, so SDK names that merely
# contain it pass.
def _blocked_terms():
    terms = [t for t in os.environ.get("STACK_BLOCKED_TERMS", "").split(",")]
    f = ROOT / ".blocked-terms"
    if f.exists():
        terms += f.read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in terms if t.strip() and not t.strip().startswith("#")]


def _brand_re():
    terms = _blocked_terms()
    if not terms:
        return None
    alts = "|".join(r"[\s_-]*".join(map(re.escape, t.split())) for t in terms)
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?![a-z])", re.I)


BRAND_RE = _brand_re()
TOOLING_BRAND_ALLOW = {"scripts/safety_check.py": None}
SVG_NS_RE = re.compile(r'xmlns(:\w+)?="[^"]*"')  # namespace declarations are identifiers, not links
TEXT_ASSET_SUFFIXES = {".svg", ".json", ".md", ".txt", ".csv"}


# data/ keeps the primary store source for each company name and icon, so store lookup and image
# hosts are expected there (and only there).
DATA_ALLOWED_HOSTS = {"itunes.apple.com", "apps.apple.com", "play.google.com", "play-lh.googleusercontent.com"}
DATA_ALLOWED_HOST_RE = re.compile(r"^is\d+-ssl\.mzstatic\.com$")


def data_host_ok(h: str) -> bool:
    h = h.lower()
    return h in DATA_ALLOWED_HOSTS or bool(DATA_ALLOWED_HOST_RE.match(h))


def export_files():
    for p in ["index.csv", "sdks.csv", "README.md"]:
        if (ROOT / p).exists():
            yield ROOT / p
    for d in ["apps", "companies", "docs", "schema"]:
        yield from sorted(x for x in (ROOT / d).rglob("*") if x.is_file())
    if (ROOT / "assets").exists():
        yield from sorted(x for x in (ROOT / "assets").rglob("*") if x.is_file() and x.suffix in TEXT_ASSET_SUFFIXES)
    if (ROOT / "data").exists():
        yield from sorted(x for x in (ROOT / "data").rglob("*") if x.is_file())


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, f"{path}.{k}"
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def main() -> int:
    known_ids: set[str] = set()
    docs = []
    for f in sorted((ROOT / "apps").glob("*/*/*/*.json")):
        d = json.loads(f.read_text())
        docs.append((f, d))
        for v in (d["app"]["store_id"], d["app"]["bundle_id"]):
            if v:
                known_ids.add(v)
        known_ids.update(d["stack"]["privacy"]["android_permissions"])
        # Brand names with a dot in them are app or company names, not hosts.
        for label in (d["app"]["name"], d["app"]["company"]["name"] or ""):
            known_ids.update(DOTTED_RE.findall(label))

    res = {k: [] for k in ["non_public_versions", "urls", "hostnames", "emails", "key_like", "banned_keys", "brand_words",
                           "internal_words_in_text"]}
    for f, d in docs:
        if not is_public_store_version(d["version"]) or INTERNAL_WORD_RE.search(f.name):
            res["non_public_versions"].append(str(f.relative_to(ROOT)))
        for k, p in walk_keys(d):
            if k in BANNED_KEYS:
                res["banned_keys"].append(f"{f.relative_to(ROOT)}:{p}")
    with open(ROOT / "index.csv") as fh:
        for row in csv.DictReader(fh):
            if not is_public_store_version(row["version"]):
                res["non_public_versions"].append(f"index.csv:{row['version']}")

    for f in export_files():
        text = f.read_text(errors="replace")
        if f.suffix == ".svg":
            text = SVG_NS_RE.sub("", text)
        rel = str(f.relative_to(ROOT))
        in_data = rel.startswith("data/")
        res["urls"] += [f"{rel}: {u}" for u in find_urls(text)
                        if not (in_data and data_host_ok(re.sub(r"^[a-z]+://([^/:?#]+).*$", r"\1", u, flags=re.I)))]
        res["hostnames"] += [f"{rel}: {h}" for h in find_hosts(text, known_ids) if not (in_data and data_host_ok(h))]
        res["emails"] += [f"{rel}: {e}" for e in find_emails(text)]
        res["key_like"] += [f"{rel}: {k[:6]}...({len(k)} chars)" for k in find_keys(text)]
        for m in (BRAND_RE.finditer(text) if BRAND_RE else []):
            res["brand_words"].append(f"{rel}:{text[: m.start()].count(chr(10)) + 1}: {m.group(0)}")
        for m in INTERNAL_WORD_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            res["internal_words_in_text"].append(f"{rel}:{line}: {m.group(0)}")

    tooling = []
    for d in ["scripts", ".github"]:
        for f in sorted(x for x in (ROOT / d).rglob("*") if x.is_file() and x.suffix in {".py", ".yml", ".md", ".sh", ".txt"}):
            text = f.read_text(errors="replace")
            hits = find_urls(text) + find_emails(text) + find_hosts(text) + [k[:6] for k in find_keys(text)]
            tooling += [f"{f.relative_to(ROOT)}: {h}" for h in hits if h not in TOOLING_ALLOW]
            rel = f.relative_to(ROOT).as_posix()
            allowed = TOOLING_BRAND_ALLOW.get(rel, set())
            if allowed is not None:
                tooling += [f"{rel}: brand word {m.group(0)}" for m in (BRAND_RE.finditer(text) if BRAND_RE else [])
                            if re.sub(r"[\s_-]", "", m.group(0).lower()) not in allowed]

    print(f"scanned {len(docs)} version files")
    failed = False
    for k, v in res.items():
        print(f"{k}: {len(v)}")
        if k == "internal_words_in_text":
            # Informational: these words also occur in SDK names (e.g. LeakCanary) and company
            # names. Versions are what must be 0 and are checked above.
            by_file: dict[str, int] = {}
            for x in v:
                by_file[x.split(":")[0]] = by_file.get(x.split(":")[0], 0) + 1
            for f, n in sorted(by_file.items(), key=lambda kv: -kv[1])[:10]:
                print(f"  {f}: {n}")
            continue
        for x in v[:20]:
            print(f"  {x}")
        if v:
            failed = True
    print(f"tooling (scripts/, .github/) unexpected hits: {len(tooling)}")
    for x in tooling[:20]:
        print(f"  {x}")
    return 1 if failed or tooling else 0


if __name__ == "__main__":
    sys.exit(main())
