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
