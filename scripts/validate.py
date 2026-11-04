#!/usr/bin/env python3
"""Validate every apps/**/*.json (including latest.json) against schema/app-version.schema.json.
Needs `pip install jsonschema`."""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
schema = json.loads((ROOT / "schema" / "app-version.schema.json").read_text())
Draft202012Validator.check_schema(schema)
v = Draft202012Validator(schema)
files = sorted((ROOT / "apps").glob("*/*/*/*.json"))
bad = 0
for f in files:
    errs = list(v.iter_errors(json.loads(f.read_text())))
    if errs:
        bad += 1
        print(f"{f.relative_to(ROOT)}: {errs[0].json_path}: {errs[0].message}")
print(f"validated {len(files)} files, {bad} invalid")
sys.exit(1 if bad or not files else 0)
