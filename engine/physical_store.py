"""
Static physical-attributes store for the Journal Square monitor.

Physical facts — square footage above all — are immutable per unit. They are
modeled ONCE and kept static; the daily scrape carries only pricing and
availability. SF is merged in from here at ingest time. See DECISIONS.md s.4.

Two access patterns:
  sqft_for(building, unit) -> int | None
      exact per-unit SF if known; else, for buildings configured with a
      line_pattern (e.g. The Journal, whose unit numbers encode floor+stack),
      the unit's stack-line SF; else None.
  learn(building, unit, sqft)
      record SF seen in a live feed, so SF-publishing buildings populate the
      store automatically and coverage grows over time with no extra effort.

The store is a small JSON file committed to the repo (physical_attributes.json),
owned and grown by the daily workflow exactly like the database.
"""
import json, os, re

import paths
HERE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = paths.config_path("physical_attributes.json")

_EMPTY = {"_meta": {}, "buildings": {}}


def load(path=None):
    path = path or STORE_PATH
    try:
        with open(path) as f:
            d = json.load(f)
        d.setdefault("buildings", {})
        return d
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(_EMPTY))


def save(store, path=None):
    path = path or STORE_PATH
    with open(path, "w") as f:
        json.dump(store, f, indent=2)


def _line_of(b, unit):
    pat = b.get("line_pattern")
    if not pat or not unit:
        return None
    m = re.match(pat, str(unit).strip())
    return m.group(2) if m else None


def _canon(unit):
    """Canonical unit key, zero-padding-insensitive: '0615' -> '615', '615' -> '615'.
    The public scrape and the RealPage harvest pad Greyson unit numbers differently
    (listed '615' vs harvested '0615'), so they must compare equal."""
    s = str(unit).strip()
    c = s.lstrip("0")
    return c if c else s


def sqft_for(store, slug, unit):
    """Exact per-unit SF if known, else stack-line SF, else None.
    Unit matching is zero-padding-insensitive so a listed '615' picks up SF
    harvested under '0615' (and vice versa)."""
    b = store.get("buildings", {}).get(slug)
    if not b:
        return None
    units = b.get("units", {})
    u = units.get(str(unit))
    if u and u.get("sqft"):
        return u["sqft"]
    cu = _canon(unit)
    for k, rec in units.items():
        if _canon(k) == cu and rec.get("sqft"):
            return rec["sqft"]
    line = _line_of(b, unit)
    if line:
        return b.get("lines", {}).get(line)
    return None


def learn(store, slug, unit, sqft=None, beds=None, baths=None):
    """Record physical attributes observed in a live feed (SF, beds, baths).
    Returns True if the store changed. Each field is individually immutable —
    an existing value is never overwritten; the first good reading wins, and
    disagreements are left for the canary to flag."""
    if not unit or (sqft is None and beds is None and baths is None):
        return False
    b = store.setdefault("buildings", {}).setdefault(slug, {})
    rec = b.setdefault("units", {}).setdefault(str(unit), {})
    changed = False
    if sqft is not None and not rec.get("sqft"):
        rec["sqft"] = int(sqft); changed = True
    if beds is not None and rec.get("beds") is None:
        rec["beds"] = beds; changed = True
    if baths is not None and rec.get("baths") is None:
        rec["baths"] = baths; changed = True
    return changed


def enrich(store, slug, units):
    """Fill missing sqft on a list of listing dicts from the store, and learn any
    sqft they already carry. Mutates in place; returns (filled, learned) counts."""
    filled = learned = 0
    for u in units:
        if learn(store, slug, u.get("unit"), u.get("sqft"), u.get("beds"), u.get("baths")):
            learned += 1
        if not u.get("sqft"):
            sf = sqft_for(store, slug, u.get("unit"))
            if sf:
                u["sqft"] = sf
                filled += 1
    return filled, learned
