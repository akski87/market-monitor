#!/usr/bin/env python3
"""Create + populate the `unit_mix` table for the active MARKET from its config.

Per-building bedroom census (Studio/1BR/2BR/3BR counts, totals, shares, sourcing
basis) — REFERENCE data, not scraped. Source is markets/<slug>/config/unit_mix.json:

    {"rows": [{"building","studio","br1","br2","br3","basis","note"}, ...],
     "avg_sf": {"<building>": <int>, ...}}

Idempotent (drops + reseeds). No-op if the market ships no unit_mix.json.

    MARKET=journal-square python engine/seed_unit_mix.py
"""
import sqlite3, os, json
import paths

SCHEMA = """
DROP TABLE IF EXISTS unit_mix;
CREATE TABLE unit_mix (
    building     TEXT PRIMARY KEY,
    studio       INTEGER,
    br1          INTEGER,
    br2          INTEGER,
    br3          INTEGER,
    total        INTEGER,
    studio_pct   REAL,
    br1_pct      REAL,
    br2_pct      REAL,
    br3_pct      REAL,
    basis        TEXT,
    is_sourced   INTEGER,     -- 1 = real sourced mix, 0 = estimated
    note         TEXT,
    avg_sf       INTEGER      -- whole-building avg unit SF (all units) where sourced; else NULL
);
"""


def main():
    cfg_path = paths.config_path("unit_mix.json")
    if not os.path.exists(cfg_path):
        print(f"No unit_mix.json for market '{paths.market_slug()}' — skipping unit_mix seed.")
        return
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    rows, avg_sf = cfg.get("rows", []), cfg.get("avg_sf", {})

    c = sqlite3.connect(paths.db_path())
    c.executescript(SCHEMA)
    for r in rows:
        s, b1, b2, b3 = r["studio"], r["br1"], r["br2"], r["br3"]
        total = s + b1 + b2 + b3
        pct = lambda n: round(n / total, 4) if total else None
        basis = r.get("basis", "")
        c.execute("""INSERT INTO unit_mix
            (building,studio,br1,br2,br3,total,studio_pct,br1_pct,br2_pct,br3_pct,basis,is_sourced,note,avg_sf)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["building"], s, b1, b2, b3, total, pct(s), pct(b1), pct(b2), pct(b3),
             basis, 0 if basis == "Estimated" else 1, r.get("note", ""), avg_sf.get(r["building"])))
    c.commit()
    n   = c.execute("SELECT COUNT(*) FROM unit_mix").fetchone()[0]
    src = c.execute("SELECT COUNT(*) FROM unit_mix WHERE is_sourced=1").fetchone()[0]
    tot = c.execute("SELECT SUM(total) FROM unit_mix").fetchone()[0]
    print(f"unit_mix seeded for '{paths.market_slug()}': {n} buildings ({src} sourced), {tot:,} units.")
    c.close()


if __name__ == "__main__":
    main()
