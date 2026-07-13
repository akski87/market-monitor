#!/usr/bin/env python3
"""Stamford — per-market extractors for the shared engine.

Harbor Point spans four operators on three platforms; all are wired as PYFETCH
(Python-side fetchers) so the engine's browser loop skips them.

  BLT (Beacon/NV/Escape/Allure/Opus/Anthem)  — one public AppFolio listings page
      (server HTML, plain GET); per-unit; mapped to building by street address.
  AJH (Infinity/121 Towne/101 Park Place)     — WordPress floor-plan pages (plain
      GET); floor-plan level: beds/baths/SF, starting rent, and a "N UNITS
      AVAILABLE" count -> N synthetic units at the floor plan's starting rent.
  GAIA (Postmark/111/Vault/The Key) + Greystar (Harbor Landing) — Yardi SecureCafe
      availableunits.aspx; per-unit, but anti-bot -> fetched through Zyte
      (ZYTE_API_KEY), falling back to a direct GET when the key is absent.
"""
import os, re, json, base64, urllib.request, html as _H

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_cache = {}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
    return urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore")


def _zyte_get(url):
    """Fetch an anti-bot page via Zyte's browser transport; direct GET if no key."""
    key = os.environ.get("ZYTE_API_KEY")
    if not key:
        return _get(url)
    body = json.dumps({"url": url, "browserHtml": True, "geolocation": "US"}).encode()
    req = urllib.request.Request("https://api.zyte.com/v1/extract", data=body, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode((key + ":").encode()).decode())
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("browserHtml", "") or ""


def _cached(key, url, fetch):
    if key not in _cache:
        _cache[key] = fetch(url)
    return _cache[key]


# ---- BLT: AppFolio listings (one page -> 6 buildings, mapped by address) ------
_APPFOLIO = "https://bltliveworkplay.appfolio.com/listings"
_ADDR2SLUG = {
    "850 Pacific Street": "allure_hp", "880 Pacific Street": "escape_hp",
    "900 Pacific Street": "opus_hp", "100-110 Commons Park North": "nv_hp",
    "1 Harbor Point Road": "beacon_hp", "2 Harbor Point Road South": "anthem_hp",
}


def _parse_appfolio(h):
    out = []
    for b in re.split(r'class="listing-item result js-listing-item"', h)[1:]:
        m = re.search(r'alt="([^"]+)"', b)
        if not m:
            continue
        alt = _H.unescape(m.group(1))
        if "Stamford" not in alt:
            continue
        slug = _ADDR2SLUG.get(alt.split(", Apt")[0].split(",")[0].strip())
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


def _blt(slug):
    return lambda: [r for r in _parse_appfolio(_cached("appfolio", _APPFOLIO, _get)) if r["slug"] == slug]


# ---- AJH: WordPress floor-plan pages (floor-plan level + availability count) ---
_AJH_URLS = {
    "infinity_hp": "https://www.infinityharborpoint.com/floorplans/",
    "towne_121": "https://www.121towne.com/floorplans/",
    "park_place_101": "https://www.101parkplace.com/floorplans/",
}


def _parse_ajh(h):
    out = []
    for blk in re.split(r'class="floor-plan item', h)[1:]:
        cnt = re.search(r'(\d+)\s*UNITS?\s*AVAILABLE', blk, re.I)
        n = int(cnt.group(1)) if cnt else 0
        if not n:
            continue
        hm = re.search(r'<h5>([^<]+)</h5>', blk)
        fp = (hm.group(1).strip().rstrip(".") if hm else "FP")
        info = _H.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", blk[:1400])))
        studio = re.search(r'studio', info, re.I)
        bm = re.search(r'(\d+)\s*Bed', info)
        bath = re.search(r'([\d.]+)\s*Bath', info)
        sqft = re.search(r'([\d,]+)\s*sq', info, re.I)
        price = re.search(r'\$([\d,]+)', info)
        if not price:
            continue
        beds = 0 if studio else (int(bm.group(1)) if bm else None)
        for i in range(n):
            out.append({"slug": None, "unit": f"{fp}-{i+1}", "beds": beds,
                        "baths": float(bath.group(1)) if bath else None,
                        "sqft": int(sqft.group(1).replace(",", "")) if sqft else None,
                        "asking": int(price.group(1).replace(",", "")), "avail": None})
    return out


def _ajh(slug):
    return lambda: _parse_ajh(_cached("ajh:" + slug, _AJH_URLS[slug], _get))


# ---- GAIA + Greystar: Yardi SecureCafe availableunits (per-unit, via Zyte) -----
_SC_URLS = {
    "postmark": "https://postmarkapts.securecafe.com/onlineleasing/postmark-apartments/availableunits.aspx",
    "vault": "https://vaultapts.securecafe.com/onlineleasing/the-vault-apartments/availableunits.aspx",
    "harbor_point_111": "https://111harborpoint.securecafe.com/onlineleasing/111-harbor-point/availableunits.aspx",
    "the_key": "https://thekeystamford.securecafe.com/onlineleasing/the-key-at-yale-towne/availableunits.aspx",
    "harbor_landing": "https://hlandingapts.securecafe.com/onlineleasing/harbor-landing-1/availableunits.aspx",
}


def _parse_sc(h):
    txt = re.sub(r"\s+", " ", _H.unescape(re.sub(r"<[^>]+>", " ", h)))
    out = []
    for sec in re.split(r'Floor Plan :', txt)[1:]:
        hdr = sec[:120]
        studio = "Studio" in hdr
        bm = re.search(r'(\d+)\s*Bedroom', hdr)
        bath = re.search(r'([\d.]+)\s*Bath', hdr)
        beds = 0 if studio else (int(bm.group(1)) if bm else None)
        for um in re.finditer(r'#(\w+)\s+(\d{3,4})\s+\$([\d,]+)(?:\s*-\s*\$([\d,]+))?\s+(Available|\d{1,2}/\d{1,2}/\d{2,4})', sec):
            unit, sqft, lo, hi, av = um.groups()
            out.append({"slug": None, "unit": unit, "beds": beds,
                        "baths": float(bath.group(1)) if bath else None,
                        "sqft": int(sqft), "asking": int(lo.replace(",", "")),
                        "avail": None if av == "Available" else av})
    return out


def _sc(slug):
    return lambda: _parse_sc(_cached("sc:" + slug, _SC_URLS[slug], _zyte_get))


PYFETCH = {}
for _s in ("beacon_hp", "nv_hp", "escape_hp", "allure_hp", "opus_hp", "anthem_hp"):
    PYFETCH[_s] = _blt(_s)
for _s in _AJH_URLS:
    PYFETCH[_s] = _ajh(_s)
for _s in _SC_URLS:
    PYFETCH[_s] = _sc(_s)

NAV = {}
EX = {}
BASIS = {}
CONC = {}


def normalize(slug, r):
    return {"unit": r.get("unit"), "beds": r.get("beds"), "baths": r.get("baths"),
            "sqft": r.get("sqft"), "asking_rent": r.get("asking"), "price_basis": "asking",
            "available_date": r.get("avail")}
