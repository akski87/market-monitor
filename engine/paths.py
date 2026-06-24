#!/usr/bin/env python3
"""Per-market path resolution for the shared engine.

Every engine script (pipeline / scrape / build_dashboard / export_flat /
physical_store / seed_unit_mix) resolves its files through here instead of
hardcoding `journal_square.*`. The active market is chosen by the MARKET
environment variable (default: journal-square), letting one engine serve many
markets, each living under markets/<slug>/.

Layout per market:
    markets/<slug>/
      market.json          # branding + metadata (display_name, kicker, region...)
      config/              # buildings_meta.json, availability_sources.json,
                           #   physical_attributes.json, reference.json, unit_mix.json
      extractors.py        # NAV / EX / normalize / BASIS / CONC / PYFETCH
      data/                # market.db, dashboard_data.json, exports/
      site/                # generated dashboard.html, building.html (served by Pages)
"""
import os, json

# repo root = parent of this engine/ directory
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MARKET = "journal-square"


def market_slug():
    return os.environ.get("MARKET", DEFAULT_MARKET)


def market_dir(slug=None):
    return os.path.join(REPO_ROOT, "markets", slug or market_slug())


def config_path(name, slug=None):
    return os.path.join(market_dir(slug), "config", name)


def data_path(name, slug=None):
    return os.path.join(market_dir(slug), "data", name)


def site_path(name, slug=None):
    return os.path.join(market_dir(slug), "site", name)


def exports_dir(slug=None):
    return os.path.join(market_dir(slug), "data", "exports")


def db_path(slug=None):
    return os.path.join(market_dir(slug), "data", "market.db")


def extractors_path(slug=None):
    return os.path.join(market_dir(slug), "extractors.py")


def template_path(name):
    return os.path.join(REPO_ROOT, "templates", name)


def market_meta(slug=None):
    """Load markets/<slug>/market.json (branding + metadata). {} if absent."""
    p = os.path.join(market_dir(slug), "market.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}
