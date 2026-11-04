<!-- ts:begin header -->
<!-- ts:end header -->

<!-- ts:begin intro -->
<!-- ts:end intro -->

<!-- ts:begin story -->
<!-- ts:end story -->

## Explore the apps

<!-- ts:begin explore -->
<!-- ts:end explore -->

## About the data

<!-- ts:begin data-facts -->
<!-- ts:end data-facts -->

### Method

Each app version is a public store build that was downloaded and read with static analysis: the binary is
inspected for languages, frameworks, SDKs, platform targets, capabilities and privacy declarations.

### Data notes

- **Public store builds only.** Every version passes a public-store filter (`isPublicStoreVersion`).
  Pre-release channels and non-store builds are never exported. `public_store_build` is always `true`.
- **`captured_at` is when the analysis was published**, not when the binary was downloaded and not the
  store release date. `store_first_seen_at` is when the version was first seen on the store and
  `store_updated_at` is the store's own update date, when known. `exported_at` is when the file was written
  here. All times are UTC (ISO 8601, `Z`).
- **SDK lists are a floor** when `confidence.sdk_list_is_floor` is true: static analysis finds what it can
  recognise, so absence of an SDK does not prove it is not used. `binary_encrypted` (App Store FairPlay) and
  `packed` / `packers` (Android packers) mark builds where less was visible.
- **SDK confidence**: `observed` = matched directly in the binary; `inferred` = derived indirectly (for
  example from mined strings); `unknown` = older analyses without a per-item match level.
- **`inferred[]` is model-written.** Headlines and insights were written by a language model from the
  detected signals and are labelled with their method. Treat them as commentary, not measurement.
- **Inactive apps** (`app.active: false`) are no longer tracked. Their history stays here.
- **Companies** use the developer name on the store listing, exactly as shown there: the iTunes Lookup
  `artistName` for iOS (the developer shown under the app name; it can differ from the "Seller") and the
  Google Play listing's developer for Android. A store can spell a company differently per platform, and
  that spelling is kept. `data/company-sources.csv` holds the live-checked name and its source for every
  app; it overrides the source record on every export and regenerate. Names are never guessed: an app with
  no verified company is left out, and the build fails on any blank or placeholder company.
- **App icons** come from the public store listings (iTunes Lookup `artworkUrl512` for iOS, the Google
  Play listing for Android), cached at 128 px and given the same rounded corners. Each icon's source is
  kept in `data/icon-sources.csv`. An app without a verified icon is left out instead of showing a
  placeholder.
- **Not exported, by design:** network hosts and endpoints, backend and GraphQL details, certificates,
  cloud project ids, SDK config keys, on-device data and database layouts, feature flags, signing details,
  tracking domain names (only their count), and any account, key or console data.

### Layout

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
- `scripts/`: the exporter, the README and chart builder, the icon fetcher, the validator and the safety check.

### Updating

New public store versions are exported incrementally (`scripts/export.py`), then icons for new apps are
fetched (`scripts/icons.py`), this README, the charts and every app and company page are rebuilt
(`scripts/build_readme.py`), every file is validated and the safety check runs before anything is committed.
See `scripts/README.md` for the full run. Everything except the export itself works offline:
`python3 scripts/export.py --regenerate-only` rebuilds all generated files from `apps/`.

The sections between `<!-- ts:begin ... -->` and `<!-- ts:end ... -->` markers are generated. Text outside the
markers can be edited by hand and is kept on the next run. The banner is drawn by `scripts/make_banner.py`.

## License

The data (`apps/`, `companies/`, `data/`, `index.csv`, `sdks.csv` and the charts) is licensed under
[CC BY 4.0](./LICENSE-DATA): reuse it freely with attribution to "Tech Stack". The code in `scripts/` and
`docs/` is [MIT](./LICENSE). App names, icons and trademarks belong to their owners.

Found a wrong company, a missing app or a broken chart? See [CONTRIBUTING.md](./CONTRIBUTING.md).

<!-- ts:begin footer -->
<!-- ts:end footer -->
