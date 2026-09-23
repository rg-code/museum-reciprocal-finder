#!/usr/bin/env python3
"""Build the offline geocoding tables from the US Census gazetteers.

- data/zip_centroids.json      {"64111": [39.057, -94.594], ...}
  One internal point per ZIP Code Tabulation Area (~34k). Shipped to the app to
  resolve the home ZIP (residence anchor for distance rules) and the "find
  museums near" ZIP. Also used by the pipeline for sources that give a ZIP.
- pipeline/place_centroids.json {"st louis, mo": [38.636, -90.245], ...}
  One point per incorporated place / CDP, plus towns and townships from the
  county-subdivision file (~45k). Pipeline-only: geocodes sources that give
  just "City, ST" (ASTC, NARM, ROAM) without a network call.

All public domain. Places/ZCTAs change rarely, so this is run by hand (not in
the monthly workflow); bump CACHE in sw.js after rebuilding zip_centroids.json:
  python pipeline/geodata.py              # newest gazetteer year available
  python pipeline/geodata.py --year 2026
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
sys.path.insert(0, str(HERE / "adapters"))
from _common import place_key  # noqa: E402  (shared with the adapters and build.py)
GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
           "{y}_Gazetteer/{y}_Gaz_{kind}_national.zip")
DECIMALS = 3  # ~110 m — far finer than the 15-90 mi distance rules need
MAX_PLACE_SQM = 1000 * 2_589_988  # 1,000 sq mi, in m² (ALAND units)

# Trailing legal/statistical descriptors in place NAMEs ("St. Louis city").
_PLACE_SUFFIX = re.compile(
    r"\s+(city and borough|metropolitan government|metro government|consolidated government|"
    r"unified government|urban county|municipality|comunidad|zona urbana|borough|village|"
    r"town|city|cdp)$", re.I)


def _rows(text: str):
    """Gazetteer text -> dict per row. Tab-separated through 2025, pipes from 2026."""
    lines = text.splitlines()
    sep = "|" if "|" in lines[0] else "\t"
    cols = [c.strip() for c in lines[0].split(sep)]
    for line in lines[1:]:
        f = [c.strip() for c in line.split(sep)]
        if len(f) >= len(cols):
            yield dict(zip(cols, f))


def _pt(row: dict) -> List[float]:
    return [round(float(row["INTPTLAT"]), DECIMALS), round(float(row["INTPTLONG"]), DECIMALS)]


def _pt_or_none(row: dict) -> Optional[List[float]]:
    """The internal point, or None when it isn't a usable center (mostly water / huge)."""
    land, water = float(row.get("ALAND") or 0), float(row.get("AWATER") or 0)
    return None if water > land or land > MAX_PLACE_SQM else _pt(row)


def parse_gazetteer(text: str) -> Dict[str, List[float]]:
    """ZCTA gazetteer text -> {zip: [lat, lng]}."""
    out = {r["GEOID"].zfill(5): _pt(r) for r in _rows(text) if r.get("GEOID")}
    return dict(sorted(out.items()))


def parse_places(text: str) -> Dict[str, Optional[List[float]]]:
    """Place gazetteer text -> {"city, st": [lat, lng]}.

    "Nashville-Davidson metropolitan government (balance)" is also keyed as
    "nashville", "Urban Honolulu CDP" as "honolulu". When names collide in a
    state, an incorporated place (FUNCSTAT A) beats a CDP, then larger land area.
    Places whose internal point isn't a usable city center keep their name but
    get null (so the name still validates a city, and geocoding falls back to
    Nominatim): mostly water — San Francisco's point is out by the Farallones —
    or huge, like Anchorage's 1,700 sq mi.
    """
    best: Dict[str, tuple] = {}
    for r in _rows(text):
        name = re.sub(r"\s*\(balance\)$", "", r["NAME"])
        name = _PLACE_SUFFIX.sub("", name)
        names = {name, re.split(r"[-/]", name)[0].strip(), re.sub(r"^Urban ", "", name)}
        rank = (r.get("FUNCSTAT") == "A", float(r.get("ALAND") or 0))
        for n in names:
            k = place_key(n, r["USPS"])
            # Aliases (split/"Urban" forms) never displace a real place of that name.
            alias = n != name
            cand = (not alias, rank, _pt_or_none(r))
            if k not in best or cand[:2] > best[k][:2]:
                best[k] = cand
    return {k: v[2] for k, v in sorted(best.items())}


_COUSUB_SUFFIX = re.compile(r"\s+(charter township|township|town|plantation|borough)$", re.I)


def parse_cousubs(text: str) -> Dict[str, Optional[List[float]]]:
    """County-subdivision gazetteer -> {"city, st": [lat, lng]} for towns and townships.

    Fills what the place table lacks: New England towns ("Harvard, MA" — not a
    Census place, and Nominatim resolves it to the university), NY/NJ/PA/MI
    townships, and NYC boroughs. Only functioning governments (FUNCSTAT A, plus
    NYC's boroughs) — not statistical county divisions. A name used by more than
    one subdivision in a state (three "Bloomfield township"s in MI) is ambiguous
    and left out.
    """
    seen: Dict[str, List[List[float]]] = {}
    for r in _rows(text):
        nyc = r["USPS"] == "NY" and r["NAME"].endswith(" borough")
        if r.get("FUNCSTAT") != "A" and not nyc:
            continue
        name = _COUSUB_SUFFIX.sub("", r["NAME"])
        seen.setdefault(place_key(name, r["USPS"]), []).append(_pt_or_none(r))
    return {k: v[0] for k, v in sorted(seen.items()) if len(v) == 1}


def _download(kind: str, year: Optional[int]) -> str:
    import requests

    years = [year] if year else range(date.today().year, date.today().year - 4, -1)
    for y in years:
        resp = requests.get(GAZ_URL.format(y=y, kind=kind), timeout=120)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            print(f"{kind} gazetteer {y}: {name}")
            return z.read(name).decode("utf-8-sig")
    raise SystemExit(f"no {kind} gazetteer found for {list(years)}")


def _write(path: Path, table: Dict[str, List[float]], minimum: int) -> None:
    if len(table) < minimum:  # guardrail against a changed/partial file
        raise SystemExit(f"only {len(table)} entries for {path.name} — refusing to overwrite")
    path.write_text(json.dumps(table, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(table)} entries -> {path}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build ZIP and place centroid tables from Census gazetteers.")
    ap.add_argument("--year", type=int, help="gazetteer year (default: newest available)")
    args = ap.parse_args(argv)
    _write(DATA / "zip_centroids.json", parse_gazetteer(_download("zcta", args.year)), 30000)
    # A place wins over a same-named town/township (the place is the town
    # center) — unless the place has no usable point and the town does.
    towns = parse_cousubs(_download("cousubs", args.year))
    places = {**towns}
    for k, v in parse_places(_download("place", args.year)).items():
        if v is not None or towns.get(k) is None:
            places[k] = v
    _write(HERE / "place_centroids.json", dict(sorted(places.items())), 28000)


if __name__ == "__main__":
    main()
