#!/usr/bin/env python3
"""
export_flat.py  —  Publish the Journal Square database as flat, read-only files.

Reads journal_square.db (the single source of truth, written only by the daily job)
and writes plain CSV + JSON into ./exports/ so that OTHER initiatives can consume the
data without touching the database:

    exports/
      units_latest.csv / .json     every available unit at each building's latest pull
      survey_latest.csv / .json     by-type market survey (Studio/1BR/2BR/3BR + All)
      timeseries.csv  / .json       one row per snapshot date (for trend-over-time)
      manifest.json                 list of files + as_of + generated_at (read this first)

These files are committed by the daily workflow and served by GitHub Pages at
    https://<user>.github.io/<repo>/exports/<file>
A read-only dashboard fetch()es the JSON; Excel uses Data > Get Data > From Web on the CSV.

Run:  python export_flat.py
"""
import sqlite3, csv, json, os, datetime
import pipeline as P
import scrape as S
# building display name -> (conc months, lease months), from the scraper's verified BASIS
TERMS_BY_NAME = {name: (S.BASIS.get(slug, {}).get("conc_mo"), S.BASIS.get(slug, {}).get("lease_mo"))
                 for name, slug in S.SLUG.items()}

import paths
HERE = os.path.dirname(os.path.abspath(__file__))
DB   = paths.db_path()
OUT  = paths.exports_dir()
TYPES = ["Studio", "1BR", "2BR", "3BR"]

def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def latest_date_per_building(c):
    return {r["building_id"]: r["d"] for r in c.execute(
        "SELECT building_id, MAX(snapshot_date) d FROM snapshots GROUP BY building_id")}

def write_csv(name, fields, rows):
    p = os.path.join(OUT, name)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k: r.get(k) for k in fields})
    return p

def write_json(name, obj):
    json.dump(obj, open(os.path.join(OUT, name), "w"), indent=2, default=str)

def main():
    os.makedirs(OUT, exist_ok=True)
    c = conn()
    latest = latest_date_per_building(c)
    as_of = max(latest.values()) if latest else None
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    # ---- 1) units_latest : every available unit at each building's most-recent pull ----
    bmeta = {r["id"]: r for r in c.execute("SELECT * FROM buildings")}
    import physical_store as _PS
    _pstore = _PS.load()
    def _store_sf(bid, unit):
        """Feed completeness: physical facts are immutable, so a row whose ingest
        predates SF capture inherits the store's known SF (exact unit, or stack-line
        model where one exists). Same fill ingest does for new rows, applied at read."""
        try:
            return _PS.sqft_for(_pstore, bid, unit) or None
        except Exception:
            return None
    quarantine = P.suspect_listing_ids(c)
    unit_fields = ["snapshot_date","building","in_market","unit","unit_type","beds","baths",
                   "sqft","asking_rent","net_effective_rent","price_basis",
                   "concession_text","available_date","data_flag","conc_months","lease_months"]
    units = []
    for bid, d in latest.items():
        b = bmeta.get(bid, {})
        for r in c.execute("SELECT * FROM listings WHERE building_id=? AND snapshot_date=?", (bid, d)):
            units.append({
                "snapshot_date": r["snapshot_date"],
                "building": b["name"] if b else bid,
                "in_market": b["in_market"] if b else "",
                "unit": r["unit"], "unit_type": r["unit_type"],
                "beds": r["beds"], "baths": r["baths"],
                "sqft": r["sqft"] or _store_sf(bid, r["unit"]),
                "asking_rent": r["asking_rent"], "net_effective_rent": r["net_effective_rent"],
                "price_basis": r["price_basis"], "concession_text": r["concession_text"],
                "available_date": r["available_date"],
                "data_flag": "SUSPECT — excluded from averages" if r["id"] in quarantine else "",
                "conc_months": TERMS_BY_NAME.get(b["name"] if b else "", (None, None))[0],
                "lease_months": TERMS_BY_NAME.get(b["name"] if b else "", (None, None))[1],
            })
    units.sort(key=lambda u: (u["building"], u["unit_type"], str(u["unit"])))
    write_csv("units_latest.csv", unit_fields, units)
    write_json("units_latest.json", {"as_of": as_of, "generated_at": generated_at, "units": units})

    # ---- 1b) units_12mo : every (building, unit) observed in the trailing 12 months ----
    # One row per unique unit: its LATEST observation in the window, plus first/last
    # seen dates and an active flag (1 = present in the building's newest snapshot).
    # This feeds the workbook's 12-month listing sheet; it grows as daily snapshots accumulate.
    import datetime as _dt
    cutoff = (_dt.date.fromisoformat(as_of) - _dt.timedelta(days=365)).isoformat() if as_of else "1900-01-01"
    seen = {}
    for r in c.execute("SELECT * FROM listings WHERE snapshot_date>=? ORDER BY snapshot_date", (cutoff,)):
        k = (r["building_id"], r["unit"], r["unit_type"], r["sqft"])
        if k not in seen:
            seen[k] = {"first": r["snapshot_date"], "row": r}
        else:
            seen[k]["row"] = r
        seen[k]["last"] = r["snapshot_date"]
    units12 = []
    for (bid, _u, _t, _s), v in seen.items():
        r = v["row"]; b = bmeta.get(bid)
        units12.append({
            "snapshot_date": r["snapshot_date"],
            "building": b["name"] if b else bid,
            "in_market": b["in_market"] if b else "",
            "unit": r["unit"], "unit_type": r["unit_type"],
            "beds": r["beds"], "baths": r["baths"],
            "sqft": r["sqft"] or _store_sf(bid, r["unit"]),
            "asking_rent": r["asking_rent"], "net_effective_rent": r["net_effective_rent"],
            "price_basis": r["price_basis"], "concession_text": r["concession_text"],
            "available_date": r["available_date"],
            "data_flag": "SUSPECT — excluded from averages" if r["id"] in quarantine else "",
            "conc_months": TERMS_BY_NAME.get(b["name"] if b else "", (None, None))[0],
            "lease_months": TERMS_BY_NAME.get(b["name"] if b else "", (None, None))[1],
            "first_seen": v["first"], "last_seen": v["last"],
            "active": 1 if v["last"] == latest.get(bid) else 0,
        })
    units12.sort(key=lambda u: (u["building"], u["unit_type"] or "", str(u["unit"])))
    f12 = unit_fields + ["first_seen", "last_seen", "active"]
    write_csv("units_12mo.csv", f12, units12)
    write_json("units_12mo.json", {"as_of": as_of, "generated_at": generated_at, "window_start": cutoff, "units": units12})

    # ---- physical attributes (static store): one record per unit ever seen ----
    import physical_store as PS
    pstore = PS.load()
    pbuildings, pflat = [], []
    for r in c.execute("SELECT id, name, units FROM buildings"):
        pb = pstore.get("buildings", {}).get(r["id"])
        if not pb: continue
        recs = [{"unit": u, "beds": v.get("beds"), "baths": v.get("baths"), "sqft": v.get("sqft")}
                for u, v in sorted((pb.get("units") or {}).items())]
        plans = [{"plan": p, "beds": v.get("beds"), "baths": v.get("baths"), "sqft": v.get("sqft")}
                 for p, v in sorted((pb.get("plans") or {}).items())]
        pbuildings.append({"id": r["id"], "name": r["name"], "total_units": r["units"],
                           "recorded": recs, "plans": plans or None,
                           "line_pattern": pb.get("line_pattern"),
                           "lines": pb.get("lines") or None})
        for x in recs:
            pflat.append({"building": r["name"], **x})
    write_json("physical_attributes.json", {"generated_at": generated_at, "buildings": pbuildings})
    write_csv("physical_attributes.csv", ["building", "unit", "beds", "baths", "sqft"], pflat)

    # ---- 2) survey_latest : by-type roll-up across IN-MARKET, Class-A units ----
    # Pool unit-level rows (co-living buildings carry no by_type rents in the study, so
    # exclude any building whose notes flag co-living to match the dashboard's survey).
    def agg(rows):
        rows = list(rows)
        n = len(rows)
        if not n: return None
        ask = [r["asking_rent"] for r in rows if r["asking_rent"] is not None]
        net = [r["net_effective_rent"] for r in rows if r["net_effective_rent"] is not None]
        sf  = [r["sqft"] for r in rows if r["sqft"] is not None]
        a = round(sum(ask)/len(ask)) if ask else None
        nv = round(sum(net)/len(net)) if net else None
        s = round(sum(sf)/len(sf)) if sf else None
        return {"units_available": n,
                "asking_avg": a, "asking_min": min(ask) if ask else None,
                "asking_max": max(ask) if ask else None,
                "net_eff_avg": nv, "avg_sqft": s,
                "asking_psf": round(a*12/s, 2) if (a and s) else None,
                "net_eff_psf": round(nv*12/s, 2) if (nv and s) else None}
    classA = []
    for bid, d in latest.items():
        b = bmeta.get(bid, {})
        if not (b and b["in_market"]): continue
        if b and b["notes"] and "co-living" in (b["notes"] or "").lower(): continue
        classA += [r for r in c.execute("SELECT * FROM listings WHERE building_id=? AND snapshot_date=?", (bid, d)) if r["id"] not in quarantine]
    survey = []
    for t in TYPES:
        a = agg([r for r in classA if r["unit_type"] == t])
        if a: survey.append({"unit_type": t, **a})
    allrow = agg(classA)
    if allrow: survey.append({"unit_type": "All", **allrow})
    survey_fields = ["unit_type","units_available","asking_avg","asking_min","asking_max",
                     "net_eff_avg","avg_sqft","asking_psf","net_eff_psf"]
    write_csv("survey_latest.csv", survey_fields, survey)
    write_json("survey_latest.json", {"as_of": as_of, "generated_at": generated_at, "survey": survey})

    # ---- 3) timeseries : one row per snapshot date (wide, Excel/trend friendly) ----
    ts_fields = ["date","total_available","all_asking","all_net_eff"]
    for t in TYPES: ts_fields += [f"{t.lower()}_asking", f"{t.lower()}_net_eff"]
    ts = []
    for r in c.execute("SELECT * FROM market_history ORDER BY snapshot_date"):
        bt = json.loads(r["by_type_json"]) if r["by_type_json"] else {}
        comp = c.execute("SELECT ROUND(AVG(asking_rent)) a, ROUND(AVG(net_effective_rent)) n FROM listings WHERE snapshot_date=?", (r["snapshot_date"],)).fetchone()
        row = {"date": r["snapshot_date"], "total_available": r["total_available"],
               "all_asking": comp["a"], "all_net_eff": comp["n"]}
        for t in TYPES:
            cell = bt.get(t) or {}
            row[f"{t.lower()}_asking"]  = cell.get("asking")
            row[f"{t.lower()}_net_eff"] = cell.get("net")
        ts.append(row)
    write_csv("timeseries.csv", ts_fields, ts)
    write_json("timeseries.json", {"generated_at": generated_at, "timeseries": ts})

    # ---- 4) unit_mix : per-building bedroom census (reference, not time-series) ----
    um_fields = ["building","studio","br1","br2","br3","total",
                 "studio_pct","br1_pct","br2_pct","br3_pct","basis","is_sourced","note"]
    unit_mix = []
    try:
        for r in c.execute("SELECT * FROM unit_mix ORDER BY is_sourced DESC, total DESC"):
            unit_mix.append({k: r[k] for k in um_fields})
        write_csv("unit_mix.csv", um_fields, unit_mix)
        write_json("unit_mix.json", {"as_of": as_of, "generated_at": generated_at, "unit_mix": unit_mix})
    except sqlite3.OperationalError:
        pass  # table not seeded yet — run seed_unit_mix.py

    # ---- manifest : the index a reader hits first ----
    base = "exports/"
    manifest = {
        "study": "Journal Square (Jersey City, NJ) Class A multifamily market monitor",
        "as_of": as_of, "generated_at": generated_at,
        "files": {
            "units_latest":  {"csv": base+"units_latest.csv",  "json": base+"units_latest.json",
                              "rows": len(units), "desc": "Every available unit at each building's latest pull."},
            "survey_latest": {"csv": base+"survey_latest.csv", "json": base+"survey_latest.json",
                              "rows": len(survey), "desc": "By-type market survey across in-market Class A units."},
            "timeseries":    {"csv": base+"timeseries.csv",    "json": base+"timeseries.json",
                              "rows": len(ts), "desc": "One row per snapshot date for trend-over-time."},
            "units_12mo":    {"csv": base+"units_12mo.csv",  "json": base+"units_12mo.json",
                              "rows": len(units12), "desc": "One row per unique unit observed in the trailing 12 months (latest values, first/last seen, active flag)."},
            "unit_mix":      {"csv": base+"unit_mix.csv",      "json": base+"unit_mix.json",
                              "rows": len(unit_mix), "desc": "Per-building bedroom census (Studio/1BR/2BR/3BR counts, shares, sourcing basis)."},
        },
    }
    write_json("manifest.json", manifest)
    print(f"Exports written to {OUT}/  (as_of {as_of}):")
    print(f"  units_latest   {len(units)} units")
    print(f"  survey_latest  {len(survey)} rows")
    print(f"  timeseries     {len(ts)} dated snapshots")

if __name__ == "__main__":
    main()
