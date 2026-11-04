# Contributing

Thanks for helping keep Tech Stack accurate.

## Reporting a data problem

Open an issue with the app, platform and version (the path under `apps/` is ideal) and what looks
wrong: a missing or misfiled company, a wrong SDK category, a broken icon or chart. Link the public
store listing when a company name or icon is involved.

## Pull requests

- Generated files (between `<!-- ts:begin -->` / `<!-- ts:end -->` markers, `index.csv`, `sdks.csv`,
  charts, app and company pages) are rebuilt from `apps/`, so change the source or the scripts, not
  the output.
- Before opening a PR, run:

  ```
  python3 scripts/export.py --regenerate-only
  python3 scripts/validate.py        # needs: pip install jsonschema
  python3 scripts/safety_check.py
  ```

- Only public store builds belong here. Pre-release channels, non-store builds, network hosts,
  keys and any account data are never accepted.
- Code in `scripts/` and `docs/` is MIT; data is CC BY 4.0 (see `LICENSE` and `LICENSE-DATA`).
