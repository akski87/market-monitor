#!/usr/bin/env python3
"""
Journal Square scraper — every building uses a DOM extractor VALIDATED against its
live availability page (Claude-for-Chrome session, 2026-06-10). Extractors run IN
the page (Playwright page.evaluate, or Claude-for-Chrome javascript_tool) because on
most of these sites the unit number isn't present in the plain page text.

Usage (needs: pip install playwright && playwright install chromium):
    python scrape.py list      # coverage
    python scrape.py run       # navigate -> extract -> ingest -> export
"""
import json, os, re, sys, datetime
import importlib.util
import pipeline as P
import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(paths.config_path("availability_sources.json")))
BY_NAME = {b["building"]: b for b in CONFIG["buildings"]}
META = json.load(open(paths.config_path("buildings_meta.json")))["buildings"]
SLUG = {name: META[name]["slug"] for name in META}
NAME_BY_SLUG = {v: k for k, v in SLUG.items()}

# Per-market scraping logic — NAV / EX / normalize / BASIS / CONC / PYFETCH — lives
# in markets/<slug>/extractors.py and is loaded dynamically so this one engine
# serves every market. Loaded by file path (market slugs contain hyphens, which
# aren't valid in dotted import names).
def _load_market_extractors():
    spec = importlib.util.spec_from_file_location("market_extractors", paths.extractors_path())
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_MKT = _load_market_extractors()
NAV       = _MKT.NAV
EX        = _MKT.EX
BASIS     = _MKT.BASIS
CONC      = getattr(_MKT, "CONC", {k: v.get("conc") for k, v in _MKT.BASIS.items()})
PYFETCH   = getattr(_MKT, "PYFETCH", {})
normalize = _MKT.normalize


# ---- concession reader: the building pages are the source of truth ----------
_NUMWORD = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
            "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
_CONC_BAD = re.compile(r"(parking|storage|pet|gym|wifi|internet)", re.I)

def _num(tok):
    tok = tok.lower().strip()
    if tok in _NUMWORD: return float(_NUMWORD[tok])
    m = re.fullmatch(r"(\d+)\s+(\d)/(\d)", tok)        # mixed fraction: 1 1/2
    if m: return int(m.group(1)) + int(m.group(2))/int(m.group(3))
    m = re.fullmatch(r"(\d)/(\d)", tok)                  # bare fraction: 1/2
    if m: return int(m.group(1))/int(m.group(2))
    return float(tok)

def _conc_scan(text):
    """Read concession language straight off a page's text. Returns
    {text, conc_mo, lease_mo, pct} (members None where the site doesn't say),
    or None when the page carries no concession language at all."""
    if not text:
        return None
    # collapse whitespace INCLUDING newlines for pair-matching: Rose widgets state
    # the term across adjacent lines ("1 Month Free" / "12-Month Lease"); the
    # 80-char gap cap below keeps unrelated text from pairing.
    flat = re.sub(r"\s+", " ", text)
    pairs = []
    # mixed fractions first ("1 1/2"), then decimals/words — order matters so
    # "1 1/2 Months Free" reads 1.5, not 2 (425 Summit Rose widget, 2026-06-11)
    NUM = r"(\d+\s+\d/\d|\d/\d|\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    # 'X month(s) free ... Y-month lease'  (e.g. "one month free on a 13-month lease")
    for m in re.finditer(NUM + r"\s*[- ]?months?(?:[’']s)?\s*free[^.;\n]{0,80}?(\d{1,2})\s*[- ]?month\s+lease", flat, re.I):
        if not _CONC_BAD.search(flat[max(0,m.start()-30):m.end()+10]):
            pairs.append((_num(m.group(1)), int(m.group(2))))
    # 'Y-month lease ... X month(s) free' (reversed order)
    for m in re.finditer(r"(\d{1,2})\s*[- ]?month\s+lease[^.;\n]{0,60}?" + NUM + r"\s*[- ]?months?\s*free", flat, re.I):
        if not _CONC_BAD.search(flat[max(0,m.start()-30):m.end()+10]):
            pairs.append((_num(m.group(2)), int(m.group(1))))
    # tier shorthand: '1 mo (13)' / '2.5 (24)'
    for m in re.finditer(NUM + r"\s*(?:mo|month)s?\.?\s*(?:free\s*)?\(\s*(\d{1,2})\s*\)", flat, re.I):
        pairs.append((_num(m.group(1)), int(m.group(2))))
    # bare 'X month(s) free' with no lease term (e.g. banner "UP TO 2 MONTHS FREE")
    bare = None
    m = re.search(r"(?:up\s+to\s+)?" + NUM + r"\s*[- ]?months?\s*free", flat, re.I)
    if m and not _CONC_BAD.search(flat[max(0,m.start()-30):m.end()+15]):
        bare = _num(m.group(1))
    # verbatim line: first line carrying concession language
    line = next((l.strip() for l in text.split("\n")
                 if re.search(r"months?\s*free|net[ -]effective|includes concession", l, re.I)
                 and not _CONC_BAD.search(l)), None)
    if not pairs and bare is None and not line:
        return None
    if pairs:
        cm, lm = max(pairs, key=lambda p: p[1])      # governing tier = longest lease
        return {"text": (line or "")[:220] or None, "conc_mo": cm, "lease_mo": lm,
                "pct": round(cm/lm, 4)}
    return {"text": (line or "")[:220] or None, "conc_mo": bare, "lease_mo": None, "pct": None}

def fill_rents(u, slug, site_pct=None):
    """Derive the unpublished rent side ONLY when the building's exact concession
    term is verified — preferring the term read off the site at pull time
    (site_pct from _conc_scan), falling back to the audited config term.
    Otherwise leave it blank — an honest gap beats an invented discount."""
    cfg = BASIS.get(slug, {})
    cm, lm = cfg.get("conc_mo"), cfg.get("lease_mo")
    t = site_pct if (site_pct and 0 < site_pct < 1) else ((cm / lm) if (cm and lm) else None)
    a, ne = u.get("asking_rent"), u.get("net_effective_rent")
    if a and ne:
        u["price_basis"] = "both"
    elif a and not ne and t:
        u["net_effective_rent"] = round(a * (1 - t)); u["price_basis"] = "asking+derived_net"
    elif ne and not a and t and 0 < t < 1:
        u["asking_rent"] = round(ne / (1 - t)); u["price_basis"] = "net+derived_gross"
    return u



# ---- Playwright runner ------------------------------------------------------
def _goto(page,url,ms=8000):
    # 'networkidle' never fires on sites with persistent connections (chat widgets,
    # analytics keep-alives) — observed 60s timeouts in CI for MetroVue/Greyson/505
    # on 2026-06-11 while the same pages loaded fine interactively. Wait for the DOM
    # instead, then give client-side rendering a fixed settle window.
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        page.goto(url, wait_until="commit", timeout=45000)
    page.wait_for_timeout(ms)

def scrape_one(page, slug):
    # NOTE: 425 Summit moved to its Rose widget (EX path) on 2026-06-10 after the
    # marketing site embedded one with gross+net per unit. The old SecureCafe
    # floorplan drill (FP_425/URL_425/JS_425 above) is retained as a fallback only.
    if slug in EX:
        _goto(page, NAV[slug])
        return [normalize(slug,r) for r in json.loads(page.evaluate(EX[slug]))]
    return None

def run(date=None):
    from playwright.sync_api import sync_playwright
    date=date or P.today_et()
    all_units,status={},{}
    all_units=[]
    with sync_playwright() as pw:
        br=pw.chromium.launch(headless=True); page=br.new_page()
        for name,cfg in BY_NAME.items():
            slug=SLUG.get(name,name)
            units=None; last_err=None
            for attempt in (1,2):
                try:
                    units=scrape_one(page,slug); last_err=None
                    if units is None or units: break   # parsed (or no parser) — done
                except Exception as e:
                    last_err=e; units=None
                if attempt==1:
                    print(f"  {name}: empty/error on attempt 1 — retrying…"); page.wait_for_timeout(4000)
            try:
                if units is None and last_err is None:
                    status[slug]={"status":"skipped_no_parser"}; continue
                if units is None: raise last_err
                # read the building's own concession language off the page it just served
                try: scan=_conc_scan(page.evaluate("document.body.innerText"))
                except Exception: scan=None
                site_pct=(scan or {}).get("pct"); site_txt=(scan or {}).get("text")
                for u in units:
                    u["building"]=name; fill_rents(u, slug, site_pct)
                    if site_txt: u["concession_text"]=site_txt
                all_units+=units
                bcfg=BASIS.get(slug,{}); cm,lm=bcfg.get("conc_mo"),bcfg.get("lease_mo")
                cfg_pct=round(cm/lm,4) if (cm and lm) else None
                status[slug]={"status":"working","units_captured":len(units),
                              "concession_text":site_txt or bcfg.get("conc"),
                              "concession_pct":site_pct if site_pct is not None else cfg_pct,
                              "concession_source":"site" if site_pct is not None else ("site_text" if site_txt else ("config" if cfg_pct is not None else None))}
                print(f"  {name}: {len(units)} units")
            except Exception as e:
                status[slug]={"status":"error","message":str(e)[:200]}; print(f"  {name}: ERROR {e}")
        br.close()
    # Python-side fetchers (anti-bot transport, e.g. Zyte) — run outside the browser loop.
    for slug, fn in PYFETCH.items():
        name = NAME_BY_SLUG.get(slug, slug)
        try:
            u = [normalize(slug, r) for r in fn()]
            for x in u: x["building"] = name
            all_units += u
            status[slug] = {"status": "working" if u else "stub_no_data", "units_captured": len(u)}
            print(f"  {name}: {len(u)} units (zyte)")
        except Exception as e:
            status[slug] = {"status": "error", "message": str(e)[:200]}
            print(f"  {name}: ZYTE ERROR {e}")
    if all_units:
        P.ingest_snapshot(all_units,date,status); P.export()
    else:
        print("FATAL: zero units captured across all buildings - nothing ingested; exiting non-zero.")
        sys.exit(1)
    return all_units

def has_parser(slug): return slug in EX

if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else "list"
    if cmd=="list":
        for name,cfg in BY_NAME.items():
            slug=SLUG.get(name,name)
            kind="DOM-extractor (validated)" if slug in EX else "TODO"
            print(f"  {name:<26} {kind}")
    elif cmd=="run": run()
    else: print(__doc__)
