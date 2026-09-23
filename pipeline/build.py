#!/usr/bin/env python3
"""Build data/museums.json from the source adapters.

Pipeline: collect -> normalize + merge (one museum, many programs) -> geocode
(cached, optional) -> validate (guardrail) -> write museums.json + meta.json.
See docs/ARCHITECTURE.md section 7.

Each source can be collected three ways (first available wins):
  1. Manual drop  : pipeline/manual_drops/<program>/*  (ToS-safe; overrides scraping)
  2. Fixtures     : pipeline/tests/fixtures/<sample>    (offline, with --from-fixtures)
  3. Live fetch   : adapter.fetch()                     (default)

Examples:
  python pipeline/build.py --sources astc,acm                # live fetch
  python pipeline/build.py --sources astc,acm --from-fixtures --no-geocode
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
ADAPTERS = HERE / "adapters"
FIXTURES = HERE / "tests" / "fixtures"
MANUAL = HERE / "manual_drops"
DATA = HERE.parent / "data"
sys.path.insert(0, str(ADAPTERS))

import astc, acm, narm, roam, aza, ahs, timetravelers as tt  # noqa: E402
from _common import Record  # noqa: E402


# ---- Source registry -------------------------------------------------------
# fixture: how to build Records offline; live: how to fetch Records for real.
def _txt(path: Path, fn: Callable[[str], List[Record]]) -> Callable[[], List[Record]]:
    return lambda: fn(path.read_text(encoding="utf-8"))


def _json(path: Path, fn: Callable[[str], List[Record]]) -> Callable[[], List[Record]]:
    return lambda: fn(path.read_text(encoding="utf-8"))


SOURCES: Dict[str, dict] = {
    "astc": {"live": astc.fetch, "fixture": _txt(FIXTURES / "astc_sample.txt", astc.parse_text)},
    "acm":  {"live": acm.fetch,  "fixture": _json(FIXTURES / "acm_sample.json", acm.parse_json)},
    "narm": {"live": narm.fetch, "fixture": _txt(FIXTURES / "narm_sample.html", narm.parse_html)},
    "roam": {"live": roam.fetch, "fixture": _txt(FIXTURES / "roam_sample.txt", roam.parse_text)},
    "aza":  {"live": aza.fetch,  "fixture": _txt(FIXTURES / "aza_sample.txt", aza.parse_text)},
    "ahs":  {"live": ahs.fetch,  "fixture": _json(FIXTURES / "ahs_sample.json", ahs.parse_json)},
    "timetravelers": {"live": tt.fetch, "fixture": _txt(FIXTURES / "timetravelers_sample.html", tt.parse_html)},
}


# ---- Collect ---------------------------------------------------------------
def collect(sources: List[str], from_fixtures: bool = False) -> List[Record]:
    records: List[Record] = []
    for name in sources:
        spec = SOURCES.get(name)
        if not spec:
            print(f"  ! unknown source: {name}", file=sys.stderr)
            continue
        drop = _manual_drop(name)
        try:
            if drop:
                recs = drop
                origin = "manual-drop"
            elif from_fixtures:
                recs = spec["fixture"]()
                origin = "fixture"
            else:
                recs = spec["live"]()
                origin = "live"
        except Exception as e:  # noqa: BLE001 - one bad source shouldn't kill the run
            print(f"  ! {name}: {origin if 'origin' in dir() else 'collect'} failed: {e}", file=sys.stderr)
            continue
        print(f"  {name}: {len(recs)} records ({origin})")
        records.extend(recs)
    return records


def _manual_drop(program: str) -> Optional[List[Record]]:
    """Parse an association-supplied file dropped in manual_drops/<program>/ (.txt/.html/.json)."""
    folder = MANUAL / program
    if not folder.is_dir():
        return None
    spec = SOURCES[program]
    files = sorted(p for p in folder.iterdir() if p.suffix in (".txt", ".html", ".json"))
    if not files:
        return None
    # Reuse the source's fixture parser but on the dropped file.
    parser = {
        "astc": astc.parse_text, "roam": roam.parse_text, "aza": aza.parse_text,
        "acm": acm.parse_json, "narm": narm.parse_html, "timetravelers": tt.parse_html,
        "ahs": ahs.parse_json,
    }[program]
    out: List[Record] = []
    for f in files:
        out.extend(parser(f.read_text(encoding="utf-8")))
    return out


# ---- Normalize + merge -----------------------------------------------------
# Same museum, names too different to match automatically: other id -> id to merge into.
SAME_MUSEUM = {
    "tulsa-children-s-museum-discovery-lab-tulsa-ok": "discovery-lab-tulsa-ok",
    "the-epc-museum-dba-la-nube-the-shape-of-imagination-el-paso-tx":
        "la-nube-steam-discovery-center-el-paso-tx",
}
# Words that don't tell two museums in the same city apart.
_GENERIC = {"the", "a", "of", "for", "at", "and", "dba", "museum", "museums",
            "center", "centre", "experience", "kids"}


def _name_core(name: str, city: Optional[str]) -> str:
    """Distinctive words of a museum name, e.g. "Lindsay Wildlife Museum" and
    "Lindsay Wildlife Experience" -> "lindsay wildlife". The city's own words
    are dropped too ("The Muse Knoxville" -> "muse")."""
    def words(s: str) -> List[str]:
        s = s.lower().replace("’", "'").replace("'s", "").replace("&", " and ")
        return [("st" if w == "saint" else w) for w in re.findall(r"[a-z0-9]+", s)]
    drop = _GENERIC | set(words(city or ""))
    return " ".join(sorted(set(w for w in words(name) if w not in drop)))


def normalize_and_merge(records: List[Record]) -> List[dict]:
    """Merge records that describe the same physical museum into one record with
    a combined `programs` map. Keyed by slug(name, city, state); a record from
    another program also merges into a museum in the same city + state whose
    name has the same distinctive words (programs often use old/short names),
    or via SAME_MUSEUM. The first source's name and id win."""
    museums: Dict[str, dict] = {}
    by_core: Dict[tuple, str] = {}   # (city, state, name core) -> museum id
    today = date.today().isoformat()
    verified = today[:7]

    for r in records:
        key = SAME_MUSEUM.get(r.id, r.id)
        core = (r.city, r.state, _name_core(r.name, r.city))
        if key not in museums and core[2] and core in by_core:
            if r.program not in museums[by_core[core]]["programs"]:
                key = by_core[core]
        by_core.setdefault(core, key)
        m = museums.get(key)
        if not m:
            m = {
                "id": key, "name": r.name, "city": r.city, "state": r.state,
                "country": r.country, "lat": r.lat, "lng": r.lng,
                "website": r.website, "programs": {}, "sources": [], "last_seen": today,
            }
            museums[key] = m
        # A later record for the same museum may supply coords the first one lacked.
        if m.get("lat") is None and r.lat is not None:
            m["lat"], m["lng"] = r.lat, r.lng
        entry: dict = {"verified": verified}
        if r.benefit is not None:
            entry["benefit"] = r.benefit
        if r.admits is not None:
            entry["admits"] = r.admits
        m["programs"][r.program] = entry
        if r.source and r.source not in m["sources"]:
            m["sources"].append(r.source)
        if not m.get("website") and r.website:
            m["website"] = r.website

    return sorted(museums.values(), key=lambda x: x["id"])


# ---- Geocode (city-level, cached, bounded) --------------------------------
# Museums that arrive with coords (e.g. ACM) are left alone. The rest (ASTC has
# no street address in its list) are geocoded to their CITY centroid — precise
# enough for the coarse 90-mile distance rules. We key the cache by "City, ST",
# so all museums in one city share a single lookup. The step is strictly bounded
# (short timeout, per-run cap, polite delay) so it can never hang the CI job.
CACHE_PATH = HERE / "geocode_cache.json"
GEOCODE_TIMEOUT = 10          # seconds per request
GEOCODE_DELAY = 1.1          # seconds between requests (Nominatim usage policy)
GEOCODE_MAX_NEW = 500        # hard cap on new lookups per run


def geocode(museums: List[dict], enabled: bool) -> None:
    cache: Dict[str, list] = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt cache shouldn't kill the run
            cache = {}

    session = None
    new_lookups = 0
    updated = False
    for m in museums:
        if m.get("lat") is not None:          # already geocoded by its source
            continue
        key = _city_key(m)
        if not key:
            continue
        if key in cache:
            m["lat"], m["lng"] = cache[key]
            continue
        if not enabled or new_lookups >= GEOCODE_MAX_NEW:
            continue
        latlng = _nominatim_city(key, session)
        new_lookups += 1
        if latlng:
            m["lat"], m["lng"] = latlng
            cache[key] = latlng
            updated = True
            _write_cache(cache)               # persist incrementally (resumable)

    if updated:
        _write_cache(cache)


def _city_key(m: dict) -> Optional[str]:
    city, state = m.get("city"), m.get("state")
    if city and state:
        return f"{city}, {state}"
    return None


def _write_cache(cache: Dict[str, list]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def _nominatim_city(city_state: str, session) -> Optional[list]:
    """City-centroid lookup via OpenStreetMap Nominatim (free, city-level)."""
    import time

    import requests

    sess = session or requests.Session()
    time.sleep(GEOCODE_DELAY)                  # be polite / respect rate limits
    try:
        r = sess.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city_state}, USA", "format": "json", "limit": 1},
            timeout=GEOCODE_TIMEOUT,
            headers={"User-Agent": "museum-reciprocal-finder/0.2 (personal project)"},
        )
        r.raise_for_status()
        hits = r.json()
        if hits:
            return [round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)]
    except Exception as e:  # noqa: BLE001
        print(f"    geocode miss: {city_state} ({e})", file=sys.stderr)
    return None


# ---- Validate --------------------------------------------------------------
def validate(museums: List[dict], out_dir: Path, drop_tolerance: float = 0.25) -> List[str]:
    """Schema sanity + per-program count guardrail vs. the previous meta.json."""
    problems: List[str] = []
    counts = program_counts(museums)

    for m in museums:
        if not m["id"] or not m["name"]:
            problems.append(f"record missing id/name: {m}")
        if not m["programs"]:
            problems.append(f"{m['id']}: no programs")

    prev = _load_prev_counts(out_dir)
    for prog, prev_n in prev.items():
        now_n = counts.get(prog, 0)
        if prev_n >= 4 and now_n < prev_n * (1 - drop_tolerance):
            problems.append(
                f"{prog}: count dropped {prev_n} -> {now_n} (>{int(drop_tolerance*100)}%) — "
                "likely a broken source; refusing to overwrite good data"
            )
    return problems


def program_counts(museums: List[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for m in museums:
        for p in m["programs"]:
            counts[p] = counts.get(p, 0) + 1
    return counts


def _load_prev_counts(out_dir: Path) -> Dict[str, int]:
    meta = out_dir / "meta.json"
    if not meta.exists():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("counts", {}).get("by_program", {})
    except Exception:  # noqa: BLE001
        return {}


# ---- Write -----------------------------------------------------------------
def write(museums: List[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "museums.json").write_text(
        json.dumps({"museums": museums}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    meta = {
        "last_updated": date.today().isoformat(),
        "counts": {"museums": len(museums), "by_program": program_counts(museums)},
        "geocoded": sum(1 for m in museums if m["lat"] is not None),
        "schema_version": 1,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


# ---- CLI -------------------------------------------------------------------
def run(sources: List[str], from_fixtures: bool, geocode_enabled: bool, out_dir: Path) -> dict:
    print(f"Collecting from: {', '.join(sources)}")
    records = collect(sources, from_fixtures=from_fixtures)
    museums = normalize_and_merge(records)
    print(f"Merged into {len(museums)} museums")
    geocode(museums, enabled=geocode_enabled)
    problems = validate(museums, out_dir)
    if problems:
        print("VALIDATION FAILED:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        raise SystemExit(2)
    write(museums, out_dir)
    print(f"Wrote {out_dir/'museums.json'} and meta.json")
    return {"museums": len(museums), "by_program": program_counts(museums)}


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build data/museums.json from source adapters.")
    ap.add_argument("--sources", default="astc,acm",
                    help="comma-separated: astc,acm,narm,roam,aza,ahs,timetravelers")
    ap.add_argument("--from-fixtures", action="store_true",
                    help="use saved fixtures instead of live fetching (offline)")
    ap.add_argument("--no-geocode", action="store_true", help="skip the geocoding stage")
    ap.add_argument("--out", default=str(DATA), help="output directory (default: data/)")
    args = ap.parse_args(argv)
    run(
        sources=[s.strip() for s in args.sources.split(",") if s.strip()],
        from_fixtures=args.from_fixtures,
        geocode_enabled=not args.no_geocode,
        out_dir=Path(args.out),
    )


if __name__ == "__main__":
    main()
