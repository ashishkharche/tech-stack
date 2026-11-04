#!/usr/bin/env bash
# Fail unless every listed commit has author AND committer exactly
#   ashishkharche <thekharche@gmail.com>
# Commits made in the GitHub web UI (committer "GitHub <noreply@github.com>") are rejected too.
#
# Usage: scripts/check_commit_identity.sh <git rev-list arguments>
#   scripts/check_commit_identity.sh BASE..HEAD
#   scripts/check_commit_identity.sh HEAD --not --remotes=origin
set -euo pipefail

want="ashishkharche <thekharche@gmail.com>"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <rev-list arguments>" >&2
  exit 2
fi

log=$(git log --no-mailmap --format='%H%x09%an%x09%ae%x09%cn%x09%ce' "$@")

checked=0
bad=0
while IFS=$'\t' read -r sha an ae cn ce; do
  [ -n "$sha" ] || continue
  checked=$((checked + 1))
  author="$an <$ae>"
  committer="$cn <$ce>"
  if [ "$author" != "$want" ] || [ "$committer" != "$want" ]; then
    bad=$((bad + 1))
    msg="commit ${sha:0:12}: author '$author', committer '$committer' (both must be '$want')"
    if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::error::$msg"; else echo "$msg" >&2; fi
  fi
done <<< "$log"

if [ "$bad" -gt 0 ]; then
  echo "Commit identity check failed: $bad of $checked commits are not $want." >&2
  echo "Fix: git config user.name ashishkharche && git config user.email thekharche@gmail.com, then recreate the commits." >&2
  exit 1
fi
echo "Commit identity check passed: $checked commits, all $want."
