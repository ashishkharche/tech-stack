# Maintaining the dataset

Back to the [README](../README.md). The full run, with every script, is in [scripts/README.md](../scripts/README.md).

## Updating

New public store versions are exported incrementally (`scripts/export.py`), then icons for new apps are
fetched (`scripts/icons.py`), the README, the charts and every app and company page are rebuilt
(`scripts/build_readme.py`), every file is validated and the safety check runs before anything is committed.
See `scripts/README.md` for the full run. Everything except the export itself works offline:
`python3 scripts/export.py --regenerate-only` rebuilds all generated files from `apps/`.

The sections between `<!-- ts:begin ... -->` and `<!-- ts:end ... -->` markers are generated. Text outside the
markers can be edited by hand and is kept on the next run. The banner is drawn by `scripts/make_banner.py`.

Before committing, run `python3 scripts/validate.py`, `python3 scripts/safety_check.py` and
`python3 scripts/check_consistency.py`. CI (`.github/workflows/validate.yml`) runs the same checks and fails if
`python3 scripts/export.py --regenerate-only` changes any file.

## Layout

- `apps/<ios|android>/<company-slug>/<app-slug>/<version>.json`: one file per public store version.
  `latest.json` is a copy of the highest version (by version number, not capture time). Each app folder has a
  `README.md` with its icon, store link, SDKs by category and version history.
- `companies/<company-slug>.md`: apps per company, with the SDKs they share. `companies/README.md` lists every
  company.
- `data/company-sources.csv` and `data/icon-sources.csv`: the store source (URL and field) for each
  company name that the source record lacked, and for every icon.
- `index.csv`: one row per app version (platform, company, app, store id, version, captured_at, sdk_count,
  active and confidence flags).
- `sdks.csv`: each SDK and the apps whose latest version ships it.
- `assets/`: the Iso Block logo (`assets/logo/`: black for light backgrounds, white for dark; SVG, 512 px and
  32 px PNG), the banner, the badges, the charts (`assets/charts/`) and the app icons (`assets/icons/`). Charts
  and badges come in a light and a dark version, each on its own solid background.
- `schema/app-version.schema.json`: JSON Schema every version file is validated against.
- `docs/index.html`: a static filter page over `index.csv`. Serve it with GitHub Pages (Settings > Pages >
  deploy from `main`, folder `/docs`) or open it locally: `python3 -m http.server 8000`, then
  `http://localhost:8000/docs/`.
- `docs/data-notes.md` and `docs/maintaining.md`: these notes.
- `scripts/`: the exporter, the README and chart builder, the icon fetcher, the validator and the safety check.
