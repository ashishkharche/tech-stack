# Scripts

All standard-library Python 3.10+, except `validate.py`, which needs `pip install jsonschema`.

| Script | What it does |
|---|---|
| `export.py` | Fetches public store tech-stack versions and writes `apps/`, then rebuilds every generated file. |
| `generate.py` | Rebuilds `latest.json`, `index.csv` and `sdks.csv` from `apps/`, then runs `build_readme.py`. |
| `build_readme.py` | Builds `README.md` (between the `ts:begin` / `ts:end` markers), the charts in `assets/charts/`, the Iso Block logo in `assets/logo/` (light and dark SVG, 512 px and 32 px PNG) and badges, every app `README.md` and `companies/`. Fails if a chart has overlapping or clipped text. Logo PNGs need `rsvg-convert` (librsvg). |
| `make_banner.py` | Draws the banner (Geist and Geist Serif, outlined, monochrome) into `assets/banner-*.svg` / `.png`. Run by hand when the design changes: `python3 scripts/make_banner.py --font-dir <folder with Geist-Medium.ttf and GeistSerif-Regular.ttf>` (from the `geist` npm package; the fonts are not stored here). To try another logo, add `--logo new.svg` (any SVG with a viewBox; it is drawn in the text colour). |
| `svgkit.py` | The SVG chart, logo and badge helpers used by `build_readme.py`, with the brand palette and fonts. |
| `icons.py` | Fetches missing app icons (128 px) from the public store listings into `assets/icons/`, keeps each one's source in `data/icon-sources.csv` and rounds their corners (`pngkit.py`). Failures are retried after 7 days. `--refresh-all` fetches every icon again; `--round-all` rounds every cached PNG icon. |
| `companies.py` | Company names: placeholder checks and `data/company-sources.csv`, the store source for each company name the source record lacks. `--apply` moves apps filed without a company to their verified company and leaves out the rest (`generate.py` runs it too). |
| `transform.py` | The field allowlist: source API payload to one version document. `upgrade_doc()` moves older files to the current schema. |
| `stacklib.py` | Shared helpers: API client, version compare, JSON writer, `SCHEMA_VERSION`. |
| `leakscan.py` | URL / hostname / email / key-like patterns used by the transform and the safety check. |
| `validate.py` | Validates every version file against `schema/app-version.schema.json`. |
| `check_consistency.py` | Checks that `index.csv`, `sdks.csv`, every `latest.json`, `companies/` and the README headline numbers agree with the version files. Standard library only. |
| `safety_check.py` | Fails if the export has non-public versions, URLs, hostnames, emails, key-like strings, source-site brand names or never-export fields. |

## Running an export against the API

```
export STACK_API_BASE=<base-url>    # base URL of the source API
export STACK_API_KEY=...            # the source API key; never commit it
python3 scripts/export.py --source api --max-requests 900
python3 scripts/icons.py              # only fetches icons that are missing
python3 scripts/build_readme.py       # README, charts, banner, app and company pages
python3 scripts/validate.py
python3 scripts/safety_check.py
```

The API run is incremental. It lists apps (`/api/v1/apps`) and the latest analysed build per app
(`/api/v1/tech-stack`), then for each app whose latest version is not in `apps/` yet it reads
`/api/v1/tech-stack/{id}` (which lists that app's public versions), `/api/v1/apps/{id}/versions`
for store dates, and `/api/v1/tech-stack/{id}?version=` for each missing version. Calls are spaced
1.2 s apart (50 a minute) and capped per run, and the run stops early if the daily quota header
gets low. Each call costs 1 unit, so a normal day is a handful of calls; a run that stops on
the cap simply continues the next day.

## Schema

Version files are `schema_version` 1.1. `generate.py` (and so every `export.py` run, including
`--regenerate-only`) upgrades any 1.0 file it finds: it drops the source URLs, sets `company.source`
to `store_listing_developer` and rewords the `inferred[]` note.

## Initial export from raw JSON

`--source raw --raw-dir DIR` reads three JSON files (`stacks.json`, `apps.json`, `versions.json`)
exported read-only from the source database: the analysed builds with their payloads, the apps that
have one, and their store versions. See `load_raw()` in `export.py` for the fields each file needs.

The raw payload still contains fields that are never exported, so keep those files out of this
repo (`.gitignore` covers `raw/`). The allowlist in `transform.py` decides what is written.
