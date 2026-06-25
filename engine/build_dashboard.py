#!/usr/bin/env python3
"""Render the per-market site bundle from the shared templates + the market's data.

For the active MARKET (see engine/paths.py) this:
  1. renders templates/dashboard.html  -> markets/<slug>/site/dashboard.html
       (substitutes {{SITE_TITLE}}/{{KICKER}} from market.json, injects
        data/dashboard_data.json into the /*DATA_START*/.../*DATA_END*/ block)
  2. renders templates/building.html   -> markets/<slug>/site/building.html
       (branding only; this page fetches its data at runtime)
  3. copies dashboard_data.json + exports/ into site/ so the runtime fetches in
     building.html (and the dashboard's freshness fetch) resolve from one folder.

Run AFTER `pipeline.py export` and `export_flat.py` so site/ ships the latest data.

    MARKET=journal-square python engine/build_dashboard.py
"""
import re, os, json, shutil
import paths


def _brand(html, meta):
    return (html.replace("{{SITE_TITLE}}", meta.get("site_title", "Market Monitor"))
                .replace("{{H1}}", meta.get("h1", meta.get("display_name", "Market Monitor")))
                .replace("{{KICKER}}", meta.get("kicker", "")))


def main():
    slug = paths.market_slug()
    meta = paths.market_meta()
    os.makedirs(os.path.dirname(paths.site_path("x")), exist_ok=True)

    # 1. dashboard.html — branding + baked data block
    tpl  = open(paths.template_path("dashboard.html"), encoding="utf-8").read()
    data = open(paths.data_path("dashboard_data.json"), encoding="utf-8").read().strip()
    html = _brand(tpl, meta)
    html, n = re.subn(r"/\*DATA_START\*/.*?/\*DATA_END\*/",
                      lambda m: "/*DATA_START*/" + data + "/*DATA_END*/",
                      html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("Could not find the /*DATA_START*/.../*DATA_END*/ block in dashboard.html template")
    open(paths.site_path("dashboard.html"), "w", encoding="utf-8").write(html)

    # 2. building.html — branding only (loads data at runtime)
    btpl = open(paths.template_path("building.html"), encoding="utf-8").read()
    open(paths.site_path("building.html"), "w", encoding="utf-8").write(_brand(btpl, meta))

    # 3. data + exports into the deployable bundle (building.html fetches these)
    shutil.copyfile(paths.data_path("dashboard_data.json"), paths.site_path("dashboard_data.json"))
    exp_src, exp_dst = paths.exports_dir(), paths.site_path("exports")
    if os.path.isdir(exp_src):
        os.makedirs(exp_dst, exist_ok=True)
        for f in os.listdir(exp_src):
            src = os.path.join(exp_src, f)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(exp_dst, f))

    print(f"Built site for '{slug}': dashboard.html ({len(data)} bytes data) + building.html + data + exports")


if __name__ == "__main__":
    main()
