# Syncing features with `journal-square-monitor`

This platform's `engine/` was generalized from the original single-market repo
[`journal-square-monitor`](https://github.com/akski87/journal-square-monitor). That repo
stays running as the legacy Journal Square site and as a byte-fidelity reference. When a
**feature** is built there (a dashboard change, a new metric, a scraper improvement), it
should flow into this platform so every market benefits.

## File map (original root  ⇄  this repo)

| `journal-square-monitor` (root) | `market-monitor` | Notes |
|---|---|---|
| `pipeline.py` | `engine/pipeline.py` | file paths go through `engine/paths.py` here |
| `scrape.py` (generic core) | `engine/scrape.py` | `NAV`/`EX`/`normalize`/`BASIS` were lifted out |
| `scrape.py` (`NAV`/`EX`/`normalize`/`BASIS`) | `markets/journal-square/extractors.py` | per-market |
| `build_dashboard.py` | `engine/build_dashboard.py` | renders templates → `site/` here |
| `export_flat.py`, `physical_store.py`, `zyte_baldwin.py` | `engine/<same>` | paths via `engine/paths.py` |
| `seed_unit_mix.py` (data in code) | `engine/seed_unit_mix.py` + `markets/<slug>/config/unit_mix.json` | data externalized |
| `dashboard.html`, `building.html` | `templates/<same>` | branding is `{{SITE_TITLE}}`/`{{KICKER}}` here |
| `buildings_meta.json`, `availability_sources.json`, `physical_attributes.json`, `reference.json` | `markets/journal-square/config/<same>` | per-market |

## How to port a feature

A feature change touches **engine logic or a template** — never per-market data. To port it:

1. Find the original file in the map above and apply the same change to its `engine/` or
   `templates/` counterpart here.
2. The only routine adjustments:
   - **Paths**: use `paths.config_path(...)` / `paths.data_path(...)` / `paths.db_path()`
     instead of `os.path.join(HERE, "journal_square.db")` etc.
   - **Branding** in templates: keep `{{SITE_TITLE}}` / `{{KICKER}}` rather than hardcoded
     "Journal Square" strings.
   - **Per-building scraper changes** (a new extractor, a `BASIS` tweak) go in the relevant
     market's `extractors.py`, not the engine.
3. Rebuild locally to confirm, then commit:
   ```bash
   MARKET=journal-square python engine/pipeline.py export
   MARKET=journal-square python engine/export_flat.py
   MARKET=journal-square python engine/build_dashboard.py
   ```

Because the change lands in `engine/`/`templates/`, **all** markets pick it up on their next
daily run — that's the whole point of the shared-engine split.

> Direction of travel: once this platform is verified in production, new feature work can be
> done here directly (and, if still desired, back-ported to the legacy repo the same way).
