"""Patterns for things that must never appear in the export: URLs/hostnames that are not a
store, emails, and key-like strings. Used to drop unsafe model-written text at export
time and by safety_check.py before every commit. Standard library only."""
from __future__ import annotations

import re

ALLOWED_HOSTS = {"apps.apple.com", "play.google.com", "localhost"}

TLDS = {
    "com", "net", "org", "io", "ai", "app", "dev", "co", "me", "tv", "gg", "xyz", "cloud", "site", "info",
    "biz", "us", "uk", "de", "jp", "cn", "ru", "in", "fr", "br", "kr", "eu", "ly", "so", "sh", "to", "cc",
    "tech", "online", "live", "link", "page", "services", "systems", "network", "digital", "store", "shop",
    "email", "social", "games", "fm", "im", "is", "ms", "nl", "se", "es", "it", "ca", "au", "id", "vn",
}

URL_RE = re.compile(r"\b(?:https?|wss?|ftp)://[^\s\"'<>)\]]+", re.I)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
DOTTED_RE = re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+(?![A-Za-z0-9_-])")
KEY_PREFIX_RE = re.compile(
    r"(AIza[0-9A-Za-z_-]{20,}|\bsk-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*KEY-----|\bey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})"
)
LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{32,}(?![A-Za-z0-9+/_=-])")
INTERNAL_WORD_RE = re.compile(r"testflight|nightly|internal|alpha|beta|debug|adhoc|dogfood|canary|staging", re.I)


def _host_of(url: str) -> str:
    m = re.match(r"[a-z]+://([^/:?#]+)", url.replace("\\", ""), re.I)
    return (m.group(1) if m else "").lower()


def find_urls(text: str) -> list[str]:
    return [u for u in URL_RE.findall(text) if _host_of(u) not in ALLOWED_HOSTS]


def find_emails(text: str) -> list[str]:
    return EMAIL_RE.findall(text)


def find_hosts(text: str, known_ids: set[str] | frozenset = frozenset()) -> list[str]:
    """Dotted tokens that look like hostnames. Reverse-DNS identifiers (bundle ids, Java packages,
    Android permissions) and known store/bundle ids are not hosts."""
    out = []
    for tok in DOTTED_RE.findall(text):
        t = tok.strip(".").lower()
        if t in ALLOWED_HOSTS or tok in known_ids or t in known_ids:
            continue
        labels = t.split(".")
        if len(labels) < 2 or labels[-1] not in TLDS:
            continue
        if labels[0] in TLDS or labels[0] == "android":
            continue  # reverse-DNS identifier (com.example.sdk), not a hostname
        if all(re.fullmatch(r"\d+", x) for x in labels[:-1]):
            continue
        out.append(tok)
    return out


def _keyish(tok: str) -> bool:
    if "/" in tok and not re.search(r"[+=]", tok):
        return False  # path-like
    has_digit = bool(re.search(r"\d", tok))
    has_upper = bool(re.search(r"[A-Z]", tok))
    has_lower = bool(re.search(r"[a-z]", tok))
    if re.fullmatch(r"[0-9a-f]{32,}", tok):
        return True  # long hex
    return has_digit and has_upper and has_lower and not re.fullmatch(r"[A-Za-z]+(?:[-_][A-Za-z0-9]+)+", tok)


def find_keys(text: str) -> list[str]:
    hits = KEY_PREFIX_RE.findall(text)
    hits += [t for t in LONG_TOKEN_RE.findall(text) if _keyish(t)]
    return hits


def unsafe_text(text: str, banned_values: set[str] | None = None) -> bool:
    """True if free text should not be exported."""
    if not text:
        return False
    if find_urls(text) or find_emails(text) or find_hosts(text) or find_keys(text):
        return True
    if INTERNAL_WORD_RE.search(text):
        return True
    low = text.lower()
    for v in banned_values or ():
        if v and v in low:
            return True
    return False
