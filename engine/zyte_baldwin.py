#!/usr/bin/env python3
"""134 Baldwin Ave — fetch units from its Zillow listing via the Zyte API.

134 Baldwin has no first-party leasing site; it's listed only on Zillow, which is
bot-protected (PerimeterX) and unreachable from a datacenter/CI browser. Zyte's
browser+anti-ban transport clears it. Reads ZYTE_API_KEY from the environment
(a GitHub Actions secret in CI). Returns raw unit records for
scrape.normalize('baldwin_134', r): {unit, beds, baths, sqft, price, avail}.

Usage:
  ZYTE_API_KEY=... python zyte_baldwin.py            # live fetch
  python zyte_baldwin.py some_saved.html             # parse a saved page (offline)
"""
import os, json, base64, urllib.request, re, datetime, sys

ZILLOW_URL = "https://www.zillow.com/apartments/jersey-city-nj/134-baldwin-ave/Cjdy8R/"

def _zyte_browser_html(url):
    key = os.environ.get("ZYTE_API_KEY")
    if not key:
        raise RuntimeError("ZYTE_API_KEY not set")
    body = json.dumps({"url": url, "browserHtml": True, "geolocation": "US"}).encode()
    req = urllib.request.Request("https://api.zyte.com/v1/extract", data=body, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode((key + ":").encode()).decode())
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("browserHtml", "") or ""

def parse_units(html):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    fps = [None]
    def find(o):
        if fps[0] is not None:
            return
        if isinstance(o, dict):
            v = o.get("floorPlans")
            if isinstance(v, list) and v:
                fps[0] = v; return
            for x in o.values():
                find(x)
        elif isinstance(o, list):
            for x in o:
                find(x)
    find(data)
    if not fps[0]:
        return []
    out, seen = [], set()
    for fp in fps[0]:
        fbeds, fbaths = fp.get("beds"), fp.get("baths")
        for u in (fp.get("units") or []):
            price = u.get("price") or u.get("baseRent")
            if not price:
                continue
            unit = re.sub(r'^\s*(unit|apt|#)\s*', '', str(u.get("unitNumber") or ""), flags=re.I).strip()
            if not unit or unit in seen:
                continue
            seen.add(unit)
            beds = u.get("beds"); beds = fbeds if beds is None else beds
            av = u.get("availableFrom")
            try:
                ts = int(av) / 1000 if av else 0
                # epoch 0 / pre-2000 = "available now" sentinel, not a real date
                av = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if ts > 946684800 else None
            except Exception:
                av = None
            out.append({"unit": unit, "beds": beds, "baths": fbaths,
                        "sqft": u.get("sqft"), "price": int(price), "avail": av})
    return out

def fetch():
    return parse_units(_zyte_browser_html(ZILLOW_URL))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        units = parse_units(open(sys.argv[1], encoding="utf-8").read())
    else:
        units = fetch()
    print(f"{len(units)} units:")
    for x in units:
        print("  ", x)
