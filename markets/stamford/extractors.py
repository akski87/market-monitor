#!/usr/bin/env python3
"""Stamford — per-market extractors for the shared engine.

Harbor Point BLT cluster (Beacon, NV, Escape, Allure, Opus, Anthem) is served by a
single PUBLIC AppFolio listings page — server-rendered HTML, plain HTTP GET, no
browser needed. We fetch it once (module-cached), parse each listing's
rent / beds / baths / SF / availability, and map every unit to its building by
street address. Wired as PYFETCH entries (Python-side fetchers) so the engine's
browser loop skips them and the fetch runs once for the whole cluster.

Other Harbor Point operators (GAIA, AJH, Greystar) still need sources — those
buildings stay roster-only (in_market=false) until wired.
"""
import re, html as _H, urllib.request

_URL = "https://bltliveworkplay.appfolio.com/listings"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# AppFolio street address (as rendered) -> our building slug
_ADDR2SLUG = {
    "850 Pacific Street": "allure_hp",
    "880 Pacific Street": "escape_hp",
    "900 Pacific Street": "opus_hp",
    "100-110 Commons Park North": "nv_hp",
    "1 Harbor Point Road": "beacon_hp",
    "2 Harbor Point Road South": "anthem_hp",
}

_cache = {}


def _all():
    """Fetch + parse the AppFolio listings once per run (cached across the 6 slugs)."""
    if "rows" not in _cache:
        req = urllib.request.Request(_URL, headers={"User-Agent": _UA, "Accept": "text/html"})
        h = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore")
        _cache["rows"] = _parse(h)
    return _cache["rows"]


def _parse(h):
    out = []
    for b in re.split(r'class="listing-item result js-listing-item"', h)[1:]:
        m = re.search(r'alt="([^"]+)"', b)
        if not m:
            continue
        alt = _H.unescape(m.group(1))
        if "Stamford" not in alt:
            continue
        street = alt.split(", Apt")[0].split(",")[0].strip()
        slug = _ADDR2SLUG.get(street)
        if not slug:
            continue
        um = re.search(r'Apt\.?\s*([A-Za-z0-9\-]+)', alt)
        seg = _H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b[:2600])))
        rent = re.search(r'RENT \$([\d,]+)', seg)
        beds = re.search(r'(\d+)\s*bd', seg)
        studio = re.search(r'studio', seg, re.I)
        bath = re.search(r'([\d.]+)\s*ba', seg)
        sqft = re.search(r'Square Feet ([\d,]+)', seg)
        avail = re.search(r'Available (NOW|\d{1,2}/\d{1,2}/\d{2,4})', seg)
        out.append({"slug": slug, "unit": um.group(1) if um else None,
                    "beds": 0 if studio else (int(beds.group(1)) if beds else None),
                    "baths": float(bath.group(1)) if bath else None,
                    "sqft": int(sqft.group(1).replace(",", "")) if sqft else None,
                    "asking": int(rent.group(1).replace(",", "")) if rent else None,
                    "avail": None if (avail and avail.group(1) == "NOW") else (avail.group(1) if avail else None)})
    return out


def _mk(slug):
    return lambda: [r for r in _all() if r["slug"] == slug]


PYFETCH = {s: _mk(s) for s in ("beacon_hp", "nv_hp", "escape_hp", "allure_hp", "opus_hp", "anthem_hp")}
NAV = {}
EX = {}
BASIS = {}
CONC = {}


def normalize(slug, r):
    # AppFolio 'RENT' is the advertised asking rent; the feed carries no concession terms.
    return {"unit": r.get("unit"), "beds": r.get("beds"), "baths": r.get("baths"),
            "sqft": r.get("sqft"), "asking_rent": r.get("asking"), "price_basis": "asking",
            "available_date": r.get("avail")}
