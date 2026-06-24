# Market Monitor

A multi-market rental dashboard platform. One shared **engine** scrapes availability,
asking & net-effective rents, and unit-mix benchmarks for a competitive set of
buildings; each **market** is a self-contained folder of config + data. The platform
starts with **Journal Square** (Jersey City, NJ) and grows market-by-market.

Live: `https://akski87.github.io/market-monitor/`

> Generalized from the original single-market [`journal-square-monitor`](https://github.com/akski87/journal-square-monitor),
> which stays running as the legacy/reference site. See [SYNCING.md](SYNCING.md) for how
> feature changes flow between the two.

## Layout

```
engine/                     shared, market-agnostic code (the part that carries features)
  paths.py                  resolves all file paths from the MARKET env var
  pipeline.py               DB schema, seed, ingest, clean, export -> dashboard_data.json
  scrape.py                 Playwright runner; loads the active market's extractors.py
  build_dashboard.py        renders templates + data -> markets/<slug>/site/
  export_flat.py            flat CSV/JSON exports for downstream consumers
  seed_unit_mix.py          seeds the unit_mix table from the market's unit_mix.json
  physical_store.py         per-unit SF/beds/baths JSON store
  zyte_baldwin.py           Zillow-via-Zyte fetcher (transport helper)
templates/
  dashboard.html            branded with {{SITE_TITLE}}/{{KICKER}}; holds the DATA block
  building.html             per-building detail page (fetches data at runtime)
markets/
  journal-square/           market #1
    market.json             branding + metadata (display_name, kicker, region, status)
    config/                 buildings_meta, availability_sources, physical_attributes,
                            reference, unit_mix  (the editable inputs)
    extractors.py           NAV / EX / normalize / BASIS / CONC / PYFETCH for its buildings
    data/                   market.db, dashboard_data.json, exports/  (generated)
    site/                   dashboard.html + building.html + data + exports  (served by Pages)
registry.json               canonical list of markets (drives the matrix + landing page)
index.html                  national landing / market picker
.github/workflows/daily-pull.yml   matrix over registry.json markets
```

## How a daily run works (per market)

`seed` → `seed_unit_mix` → `scrape` → `clean` → `export` → `export_flat` → `build_dashboard`,
then the job commits `markets/<slug>/` back to the repo. GitHub Pages serves the result.
The active market is selected entirely by the `MARKET` environment variable.

Run any step locally (no scrape needed to rebuild from the existing DB):

```bash
MARKET=journal-square python engine/pipeline.py export
MARKET=journal-square python engine/build_dashboard.py
```

## Adding a new market

1. Add an entry to [`registry.json`](registry.json) (`slug`, `display_name`, `region`,
   `status`, `pages_path`).
2. Create `markets/<slug>/` with:
   - `market.json` — branding (`site_title`, `kicker`, `region`).
   - `config/` — `buildings_meta.json`, `availability_sources.json`,
     `physical_attributes.json`, `reference.json`, and `unit_mix.json`.
   - `extractors.py` — `NAV`, `EX`, `normalize`, `BASIS` (and optional `CONC`/`PYFETCH`)
     for that market's buildings. Use `markets/journal-square/extractors.py` as the model.
   - an empty `data/` (the first run creates `market.db` via `pipeline.py init`/`seed`).
3. The daily workflow picks it up automatically from `registry.json`; the landing page
   shows a card for it.

No engine code changes are needed to add a market.
