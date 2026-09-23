#!/usr/bin/env python3
"""Build data/zip_centroids.json from the US Census ZCTA gazetteer.

Output: {"64111": [39.045, -94.583], ...} — one internal point per ZIP Code
Tabulation Area (~34k, public domain). The app uses it to resolve a home ZIP
(residence anchor for distance rules) and a "find museums near" ZIP entirely
offline. See docs/ARCHITECTURE.md section 5.3.

ZCTAs change rarely, so this is run by hand (not in the monthly workflow):
  python pipeline/zip_centroids.py              # newest gazetteer year available
  python pipeline/zip_centroids.py --year 2026
"""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

DATA = Path(__file__).resolve().parent.parent / "data"
GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
           "{y}_Gazetteer/{y}_Gaz_zcta_national.zip")
DECIMALS = 3  # ~110 m — far finer than the 15-90 mi distance rules need


def parse_gazetteer(text: str) -> Dict[str, List[float]]:
    """Gazetteer text -> {zip: [lat, lng]}.

    Tab-separated through 2025; pipe-separated from 2026 — sniffed from the header.
    """
    lines = text.splitlines()
    sep = "|" if "|" in lines[0] else "\t"
    cols = [c.strip() for c in lines[0].split(sep)]
    iz, ilat, ilng = cols.index("GEOID"), cols.index("INTPTLAT"), cols.index("INTPTLONG")
    out: Dict[str, List[float]] = {}
    for line in lines[1:]:
        f = [c.strip() for c in line.split(sep)]
        if len(f) <= max(iz, ilat, ilng) or not f[iz]:
            continue
        out[f[iz].zfill(5)] = [round(float(f[ilat]), DECIMALS), round(float(f[ilng]), DECIMALS)]
    return dict(sorted(out.items()))


def fetch(year: Optional[int] = None) -> Dict[str, List[float]]:
    import requests

    years = [year] if year else range(date.today().year, date.today().year - 4, -1)
    for y in years:
        resp = requests.get(GAZ_URL.format(y=y), timeout=120)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            text = z.read(name).decode("utf-8-sig")
        print(f"ZCTA gazetteer {y}: {name}")
        return parse_gazetteer(text)
    raise SystemExit(f"no ZCTA gazetteer found for {list(years)}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build data/zip_centroids.json from the Census ZCTA gazetteer.")
    ap.add_argument("--year", type=int, help="gazetteer year (default: newest available)")
    ap.add_argument("--out", default=str(DATA / "zip_centroids.json"))
    args = ap.parse_args(argv)

    zips = fetch(args.year)
    if len(zips) < 30000:  # guardrail: ~34k ZCTAs nationally
        raise SystemExit(f"only {len(zips)} ZCTAs parsed — refusing to overwrite")
    Path(args.out).write_text(json.dumps(zips, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(zips)} ZIP centroids -> {args.out}")


if __name__ == "__main__":
    main()
