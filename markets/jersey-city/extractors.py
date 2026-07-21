#!/usr/bin/env python3
"""Journal Square — per-market extractors for the shared engine.

Lifted verbatim from the original single-market scrape.py (audit dates and
per-building DOM logic preserved). The engine (engine/scrape.py) loads this
module by file path and reads: NAV, EX, normalize, BASIS, CONC, PYFETCH.
"""
import zyte_baldwin

# Python-side fetchers (anti-bot transport, NOT the in-browser EX path): slug -> fn()
# returning raw unit records. Used for sites unreachable from a CI browser (Zillow).
PYFETCH = {"baldwin_134": zyte_baldwin.fetch}

# URL to navigate before running the extractor (portal content URLs where applicable)
NAV = {
  "the_journal":     "https://www.journaljc.com/availability",
  "four_twenty_five_summit": "https://availability.rosenyc.com/availability/fnhqqlif/",
  "metrovue":        "https://metrovuejc.com/availability",
  "orchard":         "https://newdev.modernspacesnyc.com/Search/Frame?buildingId=641805&useOLRBuildingId=true&olrListingsOnly=true&shouldExcludeResale=true",
  "jordan_55":       "https://newdev.modernspacesnyc.com/Search/Frame?buildingId=635066&useOLRBuildingId=true&olrListingsOnly=true&shouldExcludeResale=true",
  "baldwin_345":     "https://availability.rosenyc.com/availability/noeelbmj/",
  "greyson":         "https://www.thegreyson.com/availability",
  "summit_505":      "https://www.505summit.com/availability",
  "summit_413":      "https://www.413summit.com/availability",
  "journal_squared": "https://www.journalsquared.com/availabilities/",
  "urby":            "https://www.urby.com/location/journal-square/availability",
  "three_journal_square": "https://sightmap.com/embed/d7p1mrk2pkx",
}

# ---- validated JS extractors (each returns JSON.stringify([...])) -----------
EX = {}

# 3 Journal Square (Greystar): the marketing site embeds a SightMap availability
# map; units come from SightMap's same-origin JSON API. We navigate the embed (so
# the fetch is same-origin) and read units: unit#, SF (area), price, and beds/baths
# from the unit's floor plan. Per-unit SF is published -> in_feed grade.
EX["three_journal_square"] = r"""(async()=>{
  const API='https://sightmap.com/app/api/v1/yjp2098rwxl/sightmaps/88239';
  const res=await fetch(API,{headers:{'Accept':'application/json'}});
  const d=((await res.json())||{}).data||{};
  const fp={}; (d.floor_plans||[]).forEach(f=>fp[f.id]=f);
  const rows=(d.units||[]).map(u=>{
    const p=fp[u.floor_plan_id]||{};
    return {unit:String(u.unit_number||u.display_unit_number||'').replace(/^\s*(APT|UNIT|#)\s*/i,'').trim(),
            beds:p.bedroom_count, baths:p.bathroom_count, sqft:u.area, price:u.price};
  }).filter(r=>r.unit);
  return JSON.stringify(rows);
})()"""

def _with_fiber_sf(inner_js):
    """Wrap an extractor: merge per-unit sqft from the page's Yardi/RentCafe React
    fiber feed (apartmentdata[]) into the extractor's rows, keyed by unit number.
    Pricing semantics stay with the DOM extractor (audited); only SF is taken from
    the feed. Fails soft: no fiber / structure change => rows unchanged."""
    return r"""JSON.stringify((()=>{
  const rows=JSON.parse(""" + inner_js + r""");
  const sf=(()=>{ try{
    const cands=[...document.querySelectorAll('tr,div,li')].filter(e=>/\$[\d,]{3}/.test(e.innerText||'')&&(e.innerText||'').length<300).slice(0,8);
    for(const el of cands){
      const key=Object.keys(el).find(k=>k.startsWith('__reactFiber$'));
      if(!key) continue;
      let f=el[key],hops=0,arr=null;
      while(f&&hops<70){
        for(const p of [f.memoizedProps,f.memoizedState]){
          if(p&&typeof p==='object') for(const kk in p){
            const v=p[kk];
            if(Array.isArray(v)&&v.length>3&&v[0]&&/apartmentName/i.test(Object.keys(v[0]).join(','))){arr=v;break;}
          }
          if(arr)break;
        }
        if(arr)break; f=f.return; hops++;
      }
      if(arr){const o={};arr.forEach(u=>{const n=String(u.apartmentName||'').trim();if(n&&u.sqft)o[n]=u.sqft;});return o;}
    }
    return {};
  }catch(e){ return {}; } })();
  rows.forEach(r=>{ if(r&&r.unit&&!r.sqft&&sf[r.unit]) r.sqft=sf[r.unit]; });
  return rows; })())"""

EX["the_journal"] = _with_fiber_sf(r"""JSON.stringify((()=>{
  const L=(document.body.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean); const out=[];
  for(let i=4;i<L.length;i++){ const pm=L[i].match(/^\$([\d,]+)/);
    if(pm&&/^view$/i.test(L[i-1])){ const baths=parseFloat(L[i-2]); const t=L[i-3]||''; const unit=L[i-4]||'';
      const beds=/studio/i.test(t)?0:parseInt((t.match(/\d+/)||['0'])[0]);
      if(/^[0-9A-Z][0-9A-Z\-]{2,6}$/i.test(unit)&&/studio|bed/i.test(t))
        out.push({unit,beds,baths:isNaN(baths)?null:baths,asking:parseInt(pm[1].replace(/,/g,''))}); } }
  return out; })())""")

EX["metrovue"] = r"""JSON.stringify((()=>{
  const L=(document.body.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean); const out=[];
  for(let i=0;i<L.length;i++){ const rm=L[i].match(/^RESIDENCE:\s*(\S+)/i); if(!rm) continue;
    const unit=rm[1]; const t=L[i-1]||'';
    const beds=/studio/i.test(t)?0:parseInt((t.match(/(\d+)\s*Bed/i)||[,'0'])[1]||(t.match(/\d+/)||['0'])[0]);
    const bM=t.match(/(\d+)\s*Bath/i); const baths=bM?parseFloat(bM[1]):(beds===0?1:null);
    let sf=null,price=null,avail=null;
    for(let j=i+1;j<Math.min(i+7,L.length);j++){ if(/^RESIDENCE:/i.test(L[j])) break;
      const sm=L[j].match(/Sq\.?Ft:\s*([\d,]+)/i); if(sm) sf=parseInt(sm[1].replace(/,/g,''));
      const pm=L[j].match(/PRICE:\s*\$([\d,]+)/i); if(pm) price=parseInt(pm[1].replace(/,/g,''));
      const am=L[j].match(/AVAILABLE FROM:\s*(.+)/i); if(am) avail=am[1].trim(); }
    out.push({unit,beds,baths,sqft:sf,asking:price,avail}); }
  return out; })())"""

_MS = r"""JSON.stringify((()=>{
  const ADDR="__ADDR__";
  const L=(document.body.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean);
  const head=new RegExp('^'+ADDR.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+',\\s*(\\S+)'); const out=[];
  for(let i=0;i<L.length;i++){ const m=L[i].match(head); if(!m) continue;
    const unit=m[1]; let price=null,beds=0,baths=null;
    for(let j=i+1;j<Math.min(i+7,L.length);j++){ if(head.test(L[j])) break;
      const pm=L[j].match(/\$\s?([\d,]+)/); if(pm&&price===null) price=parseInt(pm[1].replace(/,/g,''));
      const bm=L[j].match(/^(\d+)\s*Br$/i); if(bm) beds=parseInt(bm[1]);
      const am=L[j].match(/^(\d+(?:\.\d+)?)\s*Bth$/i); if(am) baths=parseFloat(am[1]); }
    if(price) out.push({unit,beds,baths,price}); }
  return out; })())"""
EX["orchard"]   = _MS.replace("__ADDR__", "55 Orchard Street")
EX["jordan_55"] = _MS.replace("__ADDR__", "55 Jordan Avenue")

def _rose_ex(addr):
    """Rose Property availability widget extractor (rows: '<unit>\t<addr>\t<type>\t<n> BA\t<sf> Sq.Ft.\t$gross' then '$net Net Effective Rent' + date). Parameterized by the building's address pattern."""
    return r"""JSON.stringify((()=>{
  const L=(document.body.innerText||'').split('\n').map(s=>s.replace(/\s+$/,'')).filter(s=>s.trim()); const out=[];
  for(let i=0;i<L.length;i++){ if(!/""" + addr + r"""/.test(L[i])) continue;
    const p=L[i].split('\t').map(s=>s.trim()).filter(Boolean);
    const unit=p[0]; const type=p.find(x=>/studio|bed|br/i.test(x))||'';
    const beds=/studio/i.test(type)?0:parseInt((type.match(/\d+/)||['0'])[0]);
    const bM=(p.find(x=>/\bBA\b/i.test(x))||'').match(/[\d.]+/);
    const sf=parseInt((p.find(x=>/Sq\.?\s*Ft/i.test(x))||'').replace(/[^\d]/g,''))||null;
    const gross=parseInt((p.find(x=>/^\$/.test(x))||'').replace(/[^\d]/g,''))||null;
    let net=null,avail=null;
    for(let j=i+1;j<Math.min(i+8,L.length);j++){ if(/""" + addr + r"""/.test(L[j])) break;
      const nm=L[j].match(/\$([\d,]+)(?:\.\d+)?\s*Net Effective/i); if(nm) net=parseInt(nm[1].replace(/,/g,''));
      if(/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(L[j].trim())) avail=L[j].trim(); }
    out.push({unit,beds,baths:bM?parseFloat(bM[0]):null,sqft:sf,gross,net,avail}); }
  return out; })())"""

EX["baldwin_345"] = _rose_ex(r"345 Baldwin Ave\.")
EX["four_twenty_five_summit"] = _rose_ex(r"425 Summit")

EX["greyson"] = r"""JSON.stringify([...document.querySelectorAll('[class*="listingRow"]')].map(row=>{
  const f=[...row.querySelectorAll('*')].filter(e=>e.children.length===0&&e.textContent.trim()).map(e=>e.textContent.trim());
  const t=f.find(x=>/^(Studio|\d+\s*Bed)/i.test(x))||'';
  const beds=/studio/i.test(t)?0:parseInt((t.match(/\d+/)||['0'])[0]);
  const bM=(f.find(x=>/Bath/i.test(x))||'').match(/[\d.]+/);
  const pM=(f.find(x=>/\$/.test(x))||'').replace(/[^\d]/g,'');
  return {unit:f[0],beds,baths:bM?parseFloat(bM[0]):null,net:pM?parseInt(pM):null};
}).filter(r=>r.net))"""

_TABLE = r"""JSON.stringify((()=>{
  const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLowerCase();
  const trs=[...document.querySelectorAll('tr')]; let hi=-1,cells=[];
  for(let i=0;i<trs.length;i++){const cs=[...trs[i].querySelectorAll('th,td')].map(c=>norm(c.textContent));
    if(cs.some(c=>/residence/.test(c))){hi=i;cells=cs;break;}}
  if(hi<0) return [];
  const col=re=>cells.findIndex(c=>re.test(c));
  const cRes=col(/residence/),cBB=col(/bed.*bath|beds.*baths|bed\/bath/),cTot=col(/total rent/),
        cNet=col(/net/),cPrice=col(/^price/),cSF=col(/interior/);
  const money=s=>{const m=(s||'').replace(/[^\d.]/g,'');return m?Math.round(parseFloat(m)):null;};
  const out=[];
  for(let i=hi+1;i<trs.length;i++){ const c=[...trs[i].querySelectorAll('td')].map(x=>x.textContent.trim());
    if(!c.length) continue;
    let res,bb='',asking=null,net=null,sf=null;
    if(c.length===cells.length){            /* row shape matches header: exact positional map */
      res=c[cRes]; bb=c[cBB]||'';
      asking=cTot>=0?money(c[cTot]):null; net=cNet>=0?money(c[cNet]):(cPrice>=0?money(c[cPrice]):null);
      sf=cSF>=0?(parseInt((c[cSF]||'').replace(/[^\d]/g,''))||null):null;
    } else {                                /* cells OMITTED for empty columns (413 redesign,
        2026-06-11): classify each cell by content instead of position */
      res=c.find(x=>/^[A-Za-z]?\d{2,5}[A-Za-z]?$/.test(x));
      bb=c.find(x=>/\bBA\b|\bBD\b|BED|STUDIO/i.test(x))||'';
      const monies=c.filter(x=>/\$\s?\d/.test(x)).map(money).filter(v=>v!=null);
      if(monies.length>=2 && cTot>=0 && cNet>=0){asking=monies[0];net=monies[1];}
      else if(monies.length){ if(cTot<0) net=monies[0]; else asking=monies[0]; }
      const nums=c.filter(x=>x!==res && !/\$/.test(x) && /^[\d,]{3,5}$/.test(x))
                  .map(x=>parseInt(x.replace(/,/g,''))).filter(v=>v>=200&&v<=3000);
      if(nums.length) sf=nums[0];           /* first plain number = Interior SF; a second would be Exterior — ignored */
    }
    if(!res||!/^[A-Za-z]?\d{2,5}[A-Za-z]?$/.test(res)) continue;
    const beds=/studio/i.test(bb)?0:parseInt((bb.match(/(\d+)\s*Bed/i)||bb.match(/\d+/)||['0'])[0]);
    const bath=(bb.match(/(\d+(?:\.\d+)?)\s*Ba/i)||bb.match(/(\d+(?:\.\d+)?)\s*Bath/i)||[])[1];
    if(asking==null&&net==null) continue;  /* phantom row guard: unit ids with no prices (2026-06-11) */
    out.push({unit:res,beds,baths:bath?parseFloat(bath):null,asking,net,sqft:sf}); }
  return out; })())"""
EX["summit_505"] = _with_fiber_sf(_TABLE)
EX["summit_413"] = _TABLE

EX["journal_squared"] = r"""JSON.stringify([...document.querySelectorAll('article')].map(a=>{
  const L=a.innerText.split('\n').map(s=>s.trim()).filter(Boolean);
  const t=L[0]||''; const beds=/studio/i.test(t)?0:parseInt((t.match(/\d+/)||['0'])[0]);
  const b=(L.find(l=>/Bath/i.test(l))||'').match(/[\d.]+/);
  const sf=(L.find(l=>/SQ\.?\s*FT/i.test(l))||'').replace(/[^\d]/g,'');
  const p=(L.find(l=>/^\$\d/.test(l))||'').replace(/[^\d]/g,'');
  const unit=L.find(l=>/^[A-Za-z]?\d{3,4}[A-Za-z]?$/.test(l)&&!/SQ/i.test(l));
  const av=(L.find(l=>/Available/i.test(l))||'').trim();
  return {unit,beds,baths:b?parseFloat(b[0]):null,sqft:sf?parseInt(sf):null,asking:p?parseInt(p):null,avail:av};
}).filter(r=>r.asking))"""

EX["urby"] = r"""JSON.stringify([...document.querySelectorAll('.floorplan-card')].map(card=>{
  const L=card.innerText.split('\n').map(s=>s.trim()).filter(Boolean);
  const bb=L.find(l=>/Bed/i.test(l)&&/Bath/i.test(l))||'';
  const beds=parseInt((bb.match(/(\d+)\s*Bed/i)||[,'0'])[1]);
  const bath=(bb.match(/(\d+(?:\.\d+)?)\s*Bath/i)||[])[1];
  const pl=L.find(l=>/\$\d/.test(l))||''; const p=(pl.match(/\$\s?([\d,]+)/)||[])[1];
  const unit=(L.find(l=>/Apt\.?\s*\S*\d/i.test(l))||'').replace(/Apt\.?\s*/i,'').trim();
  const av=(L.find(l=>/Available/i.test(l))||'').trim();
  const conc=/includes concessions/i.test(card.innerText);
  return {unit,beds,baths:bath?parseFloat(bath):null,price:p?parseInt(p.replace(/,/g,'')):null,avail:av,conc};
}).filter(r=>r.price))"""

# 425 Summit: SecureCafe portal — drill 3 floorplan detail pages.
JS_425 = r"""JSON.stringify((()=>{ const L=(document.body.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean);
  const out=[]; let cur=null; for(const l of L){ const u=l.match(/^#\s?(\S+)/); if(u){cur=u[1];continue;}
    const p=l.match(/Starting at\s*\$([\d,]+)/i); if(p&&cur){out.push({unit:cur,price:parseInt(p[1].replace(/,/g,''))});cur=null;} }
  return out; })())"""
FP_425 = [("Studioc0m8a1a-1-Bath",0,1),("1-Bedc0m8a1a-1-Bath",1,1),("2-Bedc0m8a1a-2-Bath",2,2)]
URL_425 = "https://425summit.securecafe.com/onlineleasing/425-summit0/floorplans/"

# ---- Price basis & concession config (VERIFIED per building) -----------------
# basis: what the site's displayed price actually is. term: months-free fraction
# used to DERIVE the missing side — set ONLY when the site states the exact
# concession term in its own pricing footnote ("2 months free on a 20 month
# lease"). When a banner is vague ("up to X", "select units", no term), term is
# None and NO derivation happens: the missing side stays blank rather than
# carrying an invented discount. verified = date + where the basis was read.
BASIS = {
  "the_journal":     {"basis":"net",   "conc_mo":2,   "lease_mo":20, "conc":"2 mo free (20-mo lease)",
                      "verified":"2026-06-10 site footnote: 'Rents reflect net effective pricing with 2 months free on a 20 month lease'"},
  "greyson":         {"basis":"net",   "conc_mo":2,   "lease_mo":24, "conc":"2 mo free (24-mo lease); also 1 mo/13-mo offered",
                      "verified":"2026-06-10 site footnote: 'net effective pricing with 2 months free on a 24 month lease'"},
  "summit_413":      {"basis":"net",   "conc_mo":1,   "lease_mo":13, "conc":"1 mo free (13-mo lease)",
                      "verified":"2026-06-10 site header: 'advertised rent is net effective, reflecting one month free on a 13-month lease'"},
  "summit_505":      {"basis":"both",  "conc_mo":2.5, "lease_mo":24, "conc":"Up to 2.5 mo free (24-mo lease)",
                      "verified":"2026-06-10 site publishes Total Rent AND Net Rent columns"},
  "baldwin_345":     {"basis":"both",  "conc_mo":1,   "lease_mo":12, "conc":"1 mo free (12-mo)",
                      "verified":"2026-06-08 Rose widget publishes gross AND net-effective per unit"},
  "four_twenty_five_summit": {"basis":"both", "conc_mo":None, "lease_mo":None, "conc":"Up to 2 mo free; 'net effective rent advertised'",
                      "verified":"2026-06-10 marketing site embeds Rose widget (gross+net); footnote 'Net effective rent advertised'"},
  "journal_squared": {"basis":"asking","conc_mo":None, "lease_mo":None, "conc":"Up to 1 mo free on SELECT units (term not stated)",
                      "verified":"2026-06-10 homepage banner; availability prices plain, no net-eff footnote"},
  "metrovue":        {"basis":"asking","conc_mo":None, "lease_mo":None, "conc":"Incentives offered — unquantified ('contact leasing')",
                      "verified":"2026-06-10 availability page: plain prices, no net-eff language"},
  "orchard":         {"basis":"asking","conc_mo":None, "lease_mo":None, "conc":"1-2 mo free (14-mo) per Apr survey — no concession language on widget",
                      "verified":"2026-06-10 live widget: plain asking prices, no net-eff language"},
  "jordan_55":       {"basis":"asking","conc_mo":None, "lease_mo":None, "conc":"Up to 3 mo free + no broker fee (term not stated)",
                      "verified":"2026-06-10 site meta/header: 'Up to 3 months free & no broker fees'"},
  "urby":            {"basis":"per_unit","conc_mo":None, "lease_mo":None, "conc":"Per-unit: flagged prices include concessions (net-eff); others plain asking. 'Leasing Specials' otherwise unquantified",
                      "verified":"2026-06-10 live page: 3/21 cards flagged '* Price includes concessions.', 18/21 plain"},
}
CONC = {k: v["conc"] for k, v in BASIS.items()}

def _adate(r):
    a=(r.get("avail") or "").replace("Available","").strip()
    return a or None

def normalize(slug, r):
    c=CONC.get(slug)
    if slug=="the_journal":
        # Site displays NET-EFFECTIVE prices (footnote: "2 months free on a 20-month
        # lease"). Store as net; gross is back-computed in fill_rents via CONC_PCT.
        val=r.get("asking") if "asking" in r else r.get("price")
        d={"unit":r.get("unit"),"beds":r.get("beds"),"baths":r.get("baths"),"sqft":r.get("sqft"),
           "net_effective_rent":val,"price_basis":"net_effective","concession_text":c}
        if r.get("avail") is not None: d["available_date"]=_adate(r)
        return d
    if slug in ("metrovue","orchard","jordan_55","journal_squared","three_journal_square","baldwin_134"):
        ask=r.get("asking") if "asking" in r else r.get("price")
        d={"unit":r.get("unit"),"beds":r.get("beds"),"baths":r.get("baths"),"sqft":r.get("sqft"),
           "asking_rent":ask,"price_basis":"asking","concession_text":c}
        if r.get("avail") is not None: d["available_date"]=_adate(r)
        return d
    if slug in ("baldwin_345","four_twenty_five_summit"):
        return {"unit":r["unit"],"beds":r["beds"],"baths":r.get("baths"),"sqft":r.get("sqft"),
                "asking_rent":r.get("gross"),"net_effective_rent":r.get("net"),"price_basis":"both",
                "available_date":r.get("avail"),"concession_text":c}
        return {"unit":r["unit"],"beds":r["beds"],"baths":r.get("baths"),"sqft":r.get("sqft"),
                "asking_rent":r.get("rent"),"price_basis":"asking","available_date":r.get("avail"),"concession_text":c}
    if slug=="greyson":
        return {"unit":r["unit"],"beds":r["beds"],"baths":r.get("baths"),
                "net_effective_rent":r.get("net"),"price_basis":"net_effective","concession_text":c}
    if slug in ("summit_505","summit_413"):
        ask,net=r.get("asking"),r.get("net")
        return {"unit":r["unit"],"beds":r["beds"],"baths":r.get("baths"),"sqft":r.get("sqft"),
                "asking_rent":ask,"net_effective_rent":net,
                "price_basis":"both" if (ask and net) else "net_effective","concession_text":c}
    if slug=="urby":
        # VERIFIED 2026-06-10: pricing is PER-UNIT. Cards flagged '* Price includes
        # concessions.' show NET-EFFECTIVE; unflagged cards show plain asking rent.
        d={"unit":r["unit"],"beds":r["beds"],"baths":r.get("baths"),
           "available_date":_adate(r),"concession_text":c}
        if r.get("conc"): d["net_effective_rent"]=r.get("price"); d["price_basis"]="net_effective"
        else:             d["asking_rent"]=r.get("price");        d["price_basis"]="asking"
        return d
    return r


# ===================================================================================
# Jersey City live availability sources added 2026-07-20 (beyond the Journal Square
# Playwright extractors above). These return records ALREADY in final unit format, so
# normalize()'s `return r` fallthrough passes them through unchanged. Two proven
# transports (reused from the Stamford market):
#   - SecureCafe (Yardi) availableunits.aspx — anti-bot, fetched via Zyte in CI.
#   - AppFolio public listings — plain GET, address-mapped (Meridia's Rivet portal).
# ===================================================================================
import os as _os2, re as _re2, base64 as _b642, json as _json2, urllib.request as _url2, html as _H2

_UA2 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_cc2 = {}

def _get2(url):
    return _url2.urlopen(_url2.Request(url, headers={"User-Agent": _UA2, "Accept": "text/html"}), timeout=45).read().decode("utf-8", "ignore")

def _zyte2(url):
    key = _os2.environ.get("ZYTE_API_KEY")
    if not key:
        return _get2(url)
    body = _json2.dumps({"url": url, "browserHtml": True, "geolocation": "US"}).encode()
    req = _url2.Request("https://api.zyte.com/v1/extract", data=body, method="POST")
    req.add_header("Authorization", "Basic " + _b642.b64encode((key + ":").encode()).decode())
    req.add_header("Content-Type", "application/json")
    return _json2.loads(_url2.urlopen(req, timeout=180).read()).get("browserHtml", "") or ""

def _cached2(k, url, fetch):
    if k not in _cc2:
        _cc2[k] = fetch(url)
    return _cc2[k]

def _parse_sc2(h):   # Yardi SecureCafe availableunits (JS-rendered via Zyte) -> final unit dicts
    # Grid renders "FLOOR PLAN : A2 - 1 BEDROOM, 1 BATHROOM" then rows "#unit $lo-$hi"
    # (newer RentCafe UI carries NO sqft column). Case-insensitive; sqft optional so
    # it also handles the older server-rendered "#unit sqft $lo-$hi Available" layout.
    txt = _re2.sub(r"\s+", " ", _H2.unescape(_re2.sub(r"<[^>]+>", " ", h)))
    out = []
    for sec in _re2.split(r'FLOOR PLAN :', txt, flags=_re2.I)[1:]:
        hdr = sec[:140]
        bm = _re2.search(r'(\d+)\s*BEDROOM', hdr, _re2.I)
        bath = _re2.search(r'([\d.]+)\s*BATHROOM', hdr, _re2.I)
        beds = int(bm.group(1)) if bm else None
        for um in _re2.finditer(r'#([\w-]+)\s+(?:(\d{3,4})\s+)?\$([\d,]+)(?:\s*-\s*\$([\d,]+))?', sec):
            unit, sqft, lo, hi = um.groups()
            out.append({"unit": unit, "beds": beds, "baths": float(bath.group(1)) if bath else None,
                        "sqft": int(sqft) if sqft else None, "asking_rent": int(lo.replace(",", "")),
                        "price_basis": "asking", "available_date": None})
    return out

_SC2 = {
    "bisby": "https://bisby-rentcafewebsite.securecafe.com/onlineleasing/bisby/availableunits.aspx",
    "regent_88": "https://88regentstreet.securecafe.com/onlineleasing/88-regent-street/availableunits.aspx",
    "vyv_south": "https://vyvapts.securecafe.com/onlineleasing/vyv-properties/availableunits.aspx",
    "vyv_north": "https://vyvapts.securecafe.com/onlineleasing/vyv-properties/availableunits.aspx",
    "sable": "https://sablejc.securecafe.com/onlineleasing/sable/availableunits.aspx",
    "atlas": "https://atlasjc.securecafe.com/onlineleasing/the-atlas0/availableunits.aspx",
    "birch_house": "https://birchhousejc.securecafe.com/onlineleasing/birch-house0/availableunits.aspx",
    "hazel": "https://thehazeljc.securecafe.com/onlineleasing/hazel-je-clo/availableunits.aspx",
    "the_agnes": "https://ironstate.securecafe.com/onlineleasing/the-agnes/availableunits.aspx",
    "the_devan": "https://ironstate.securecafe.com/onlineleasing/devan-propco-llc/availableunits.aspx",
    "sawyer": "https://sawyerjerseycity.securecafe.com/onlineleasing/sawyer0/availableunits.aspx",
    "oliver_hudson": "https://oliveronthehudson.securecafe.com/onlineleasing/oliver-on-the-hudson/availableunits.aspx",
}

# VYV North & South share ONE availableunits feed (unit ids N-xxxx / S-xxxx); split by prefix.
_SC_PREFIX = {"vyv_north": "N-", "vyv_south": "S-"}

def _sc2(slug):
    url = _SC2[slug]
    pref = _SC_PREFIX.get(slug)
    def fn():
        rows = _parse_sc2(_cached2("scurl:" + url, url, _zyte2))   # key by URL so shared feeds fetch once
        return [r for r in rows if r["unit"].startswith(pref)] if pref else rows
    return fn

_MERIDIA = "https://meridiapm.appfolio.com/listings"
_AF_ADDR = {"rivet": "23 University", "rivet_26": "26 University"}

def _parse_af2(h, addr):   # AppFolio listings filtered to one building's street
    out = []
    for b in _re2.split(r'class="listing-item result js-listing-item"', h)[1:]:
        m = _re2.search(r'alt="([^"]+)"', b)
        if not m or addr not in _H2.unescape(m.group(1)):
            continue
        al = _H2.unescape(m.group(1))
        um = _re2.search(r'Apt\.?\s*([A-Za-z0-9\-]+)', al)
        seg = _H2.unescape(_re2.sub(r"\s+", " ", _re2.sub(r"<[^>]+>", " ", b[:2600])))
        rent = _re2.search(r'RENT \$([\d,]+)', seg)
        if not rent:
            continue
        beds = _re2.search(r'(\d+)\s*bd', seg)
        studio = _re2.search(r'studio', seg, _re2.I)
        bath = _re2.search(r'([\d.]+)\s*ba', seg)
        sqft = _re2.search(r'Square Feet ([\d,]+)', seg)
        av = _re2.search(r'Available (NOW|\d{1,2}/\d{1,2}/\d{2,4})', seg)
        out.append({"unit": um.group(1) if um else None, "beds": 0 if studio else (int(beds.group(1)) if beds else None),
                    "baths": float(bath.group(1)) if bath else None,
                    "sqft": int(sqft.group(1).replace(",", "")) if sqft else None,
                    "asking_rent": int(rent.group(1).replace(",", "")), "price_basis": "asking",
                    "available_date": None if (av and av.group(1) == "NOW") else (av.group(1) if av else None)})
    return out

def _af2(slug):
    return lambda: _parse_af2(_cached2("af:meridia", _MERIDIA, _get2), _AF_ADDR[slug])

PYFETCH.update({s: _sc2(s) for s in _SC2})
PYFETCH.update({s: _af2(s) for s in _AF_ADDR})

# ---- RentCafe .com public ILS mirror (buildings with no dedicated securecafe sub) ----
# Server-rendered floor-plan rows "1 Bed / 1 Bath / 675 Sqft $4,750" but RentCafe serves
# them inconsistently to plain GET (anti-bot), so fetch via Zyte. FLOOR-PLAN level: one
# synthetic unit per plan at its starting rent (available_now is a floor, not exact).
_RCM = {
    "haus25": "https://www.rentcafe.com/apartments/nj/jersey-city/haus25/default.aspx",
    "marin_351": "https://www.rentcafe.com/apartments/nj/jersey-city/351-marin-llc/default.aspx",
    "one_ten": "https://www.rentcafe.com/apartments/nj/jersey-city/one-ten/default.aspx",
    "house_100": "https://www.rentcafe.com/apartments/nj/jersey-city/100house/default.aspx",
    "the_enclave": "https://www.rentcafe.com/apartments/nj/jersey-city/the-enclave-13/default.aspx",
    "garfield_829": "https://www.rentcafe.com/apartments/nj/jersey-city/829-garfield/default.aspx",
    "cityline_east": "https://www.rentcafe.com/apartments/nj/jersey-city/cityline-jersey-city-east/default.aspx",
    "cityline_west": "https://www.rentcafe.com/apartments/nj/jersey-city/city-line-jersey-city-west/default.aspx",
    "radio_lofts": "https://www.rentcafe.com/apartments/nj/jersey-city/radio-lofts-at-hudson-house/default.aspx",
    "one_grove": "https://www.rentcafe.com/apartments/nj/jersey-city/one-grove/default.aspx",
    "dvora_175": "https://www.rentcafe.com/apartments/nj/jersey-city/dvora-175-second/default.aspx",
    "grand_235": "https://www.rentcafe.com/apartments/nj/jersey-city/235-grand/default.aspx",
    "j_295": "https://www.rentcafe.com/apartments/nj/jersey-city/295j-apartments/default.aspx",
}

def _parse_rcm(h):
    txt = _H2.unescape(_re2.sub(r"\s+", " ", _re2.sub(r"<[^>]+>", " ", h)))
    out = []
    # Floor-plan header rows. Sqft is optional and may be a range ("879 - 973 Sqft");
    # baths may be plural ("2 Baths"). Rent = the plan's starting (low) figure.
    pat = r'(Studio|\d+)\s*(?:Bed|Beds)?\s*/\s*([\d.]+)\s*Baths?\s*(?:/\s*(?:[\d,]+\s*-\s*)?([\d,]+)\s*Sq\w*\.?\s*)?\$([\d,]+)'
    for i, m in enumerate(_re2.finditer(pat, txt, _re2.I)):
        b, ba, sf, rent = m.groups()
        out.append({"unit": f"fp{i+1}", "beds": 0 if b.lower() == "studio" else int(b),
                    "baths": float(ba), "sqft": int(sf.replace(",", "")) if sf else None,
                    "asking_rent": int(rent.replace(",", "")), "price_basis": "asking", "available_date": None})
    return out

def _rc(slug):
    return lambda: _parse_rcm(_cached2("rcm:" + slug, _RCM[slug], _zyte2))

PYFETCH.update({s: _rc(s) for s in _RCM})
