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
sys.path.insert(0, str(HERE))

import astc, acm, narm, roam, aza, ahs, anca, timetravelers as tt  # noqa: E402
from _common import Record, place_key  # noqa: E402


# ---- Source registry -------------------------------------------------------
# fixture: how to build Records offline; live: how to fetch Records for real.
def _txt(path: Path, fn: Callable[[str], List[Record]]) -> Callable[[], List[Record]]:
    return lambda: fn(path.read_text(encoding="utf-8"))


def _json(path: Path, fn: Callable[[str], List[Record]]) -> Callable[[], List[Record]]:
    return lambda: fn(path.read_text(encoding="utf-8"))


SOURCES: Dict[str, dict] = {
    "astc": {"live": astc.fetch, "fixture": _txt(FIXTURES / "astc_sample.txt", astc.parse_text)},
    "acm":  {"live": acm.fetch,  "fixture": _json(FIXTURES / "acm_sample.json", acm.parse_json)},
    "narm": {"live": narm.fetch, "fixture": _txt(FIXTURES / "narm_sample.txt", narm.parse_text)},
    "roam": {"live": roam.fetch, "fixture": _txt(FIXTURES / "roam_sample.txt", roam.parse_text)},
    "aza":  {"live": aza.fetch,  "fixture": _txt(FIXTURES / "aza_sample.txt", aza.parse_text)},
    "ahs":  {"live": ahs.fetch,  "fixture": _json(FIXTURES / "ahs_sample.json", ahs.parse_json)},
    "timetravelers": {"live": tt.fetch, "fixture": _txt(FIXTURES / "timetravelers_sample.txt", tt.parse_text)},
    "anca": {"live": anca.fetch, "fixture": _txt(FIXTURES / "anca_sample.html", anca.parse_html)},
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
        module = sys.modules.get(spec["live"].__module__)
        if not drop and not from_fixtures and getattr(module, "BLOCKED_REASON", None):
            print(f"  {name}: skipped — not scraped ({module.BLOCKED_REASON}); "
                  f"add a file to pipeline/manual_drops/{name}/ to include it")
            continue
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
    """Parse association-supplied files dropped in manual_drops/<program>/.

    .txt/.json go straight to the source's parser. A .pdf (or a saved .htm/.html
    page) is turned into a sibling .txt with that adapter's own
    extract_pdf_text / extract_html_text the first time it's seen; only the .txt
    is committed (originals are gitignored — we don't republish the
    association's document), and an original with a .txt beside it is skipped
    so nothing is counted twice.
    """
    folder = MANUAL / program
    if not folder.is_dir():
        return None
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".txt", ".htm", ".html", ".json", ".pdf"))
    if not files:
        return None
    # Reuse the source's fixture parser but on the dropped file.
    parser = {
        "astc": astc.parse_text, "roam": roam.parse_text, "aza": aza.parse_text,
        "acm": acm.parse_json, "narm": narm.parse_text, "timetravelers": tt.parse_text,
        "ahs": ahs.parse_json, "anca": anca.parse_html,
    }[program]
    module = {"astc": astc, "roam": roam, "aza": aza, "acm": acm, "narm": narm,
              "timetravelers": tt, "ahs": ahs, "anca": anca}[program]
    raw_kinds = {".pdf": "extract_pdf_text", ".htm": "extract_html_text", ".html": "extract_html_text"}
    raw = set()
    for f in files:
        extract = getattr(module, raw_kinds.get(f.suffix.lower(), ""), None)
        if f.suffix.lower() == ".pdf" and not extract:
            raise ValueError(f"{program}: manual drop {f.name} is a PDF but the adapter can't read PDFs")
        if not extract:                      # e.g. an HTML page the parser reads directly
            continue
        raw.add(f)
        txt = f.with_suffix(".txt")
        if txt in files:
            continue
        data = f.read_bytes() if f.suffix.lower() == ".pdf" else f.read_text(encoding="utf-8", errors="replace")
        txt.write_text(extract(data), encoding="utf-8")
        print(f"  {program}: extracted {f.name} -> {txt.name} (commit the .txt, not the original)")
        files.append(txt)
    out: List[Record] = []
    for f in sorted(set(files) - raw):
        out.extend(parser(f.read_text(encoding="utf-8")))
    return out


# ---- Normalize + merge -----------------------------------------------------
# Same museum, names too different to match automatically: other id -> id to merge into.
SAME_MUSEUM = {
    "tulsa-children-s-museum-discovery-lab-tulsa-ok": "discovery-lab-tulsa-ok",
    "the-epc-museum-dba-la-nube-the-shape-of-imagination-el-paso-tx":
        "la-nube-steam-discovery-center-el-paso-tx",
    # Renamed / full-vs-short names across NARM, ROAM, AHS (checked 2026-09-23).
    "sheldon-swope-art-museum-terre-haute-in": "swope-art-museum-terre-haute-in",
    "pacific-asia-museum-pasadena-ca": "usc-pacific-asia-museum-pasadena-ca",
    "naples-art-naples-fl": "naples-art-institute-naples-fl",
    "the-carmel-kelly-simmons-dozier-garden-at-lemoyne-arts-tallahassee-fl": "lemoyne-arts-tallahassee-fl",
    "lake-wales-arts-center-lake-wales-fl": "lake-wales-arts-council-lake-wales-fl",
    "kentuck-art-center-northport-al": "kentuck-museum-northport-al",
    "international-arts-artists-hillyer-art-space-washington-dc":
        "international-arts-artists-hillyer-arts-space-washington-dc",
    "new-britain-youth-museum-hungerford-nature-center-kensington-ct": "hungerford-nature-center-kensington-ct",
    "samuel-p-harn-museum-of-art-gainesville-fl": "harn-museum-of-art-gainesville-fl",
    "frick-art-historical-center-pittsburgh-pa": "the-frick-pittsburgh-pittsburgh-pa",
    "graycliff-derby-ny": "frank-lloyd-wright-s-graycliff-derby-ny",
    "graycliff-conservancy-derby-ny": "frank-lloyd-wright-s-graycliff-derby-ny",
    "dunn-gardens-seattle-wa": "e-b-dunn-historic-garden-trust-dunn-gardens-seattle-wa",
    "cupertino-historical-museum-cupertino-ca": "cupertino-historical-society-and-museum-cupertino-ca",
    "sterling-and-francine-clark-art-institute-williamstown-ma": "clark-art-institute-williamstown-ma",
    "charles-schulz-museum-santa-rosa-ca": "charles-m-schulz-museum-santa-rosa-ca",
    "brandywine-conservancy-museum-of-art-chadds-ford-pa": "brandywine-museum-of-art-chadds-ford-pa",
    "fullerton-arboretum-fullerton-ca": "arboretum-and-botanical-garden-at-cal-state-fullerton-fullerton-ca",
    "lee-county-alliance-for-the-arts-fort-myers-fl": "alliance-for-the-arts-fort-myers-fl",
    "abroms-engel-institute-for-the-visual-arts-aeiva-uab-birmingham-al":
        "abroms-engel-institute-for-visual-arts-birmingham-al",
    "the-dusable-black-history-museum-and-education-center-chicago-il":
        "dusable-black-history-museum-and-educational-center-chicago-il",
    "cornell-botanic-gardens-ithaca-ny": "cornell-botanical-gardens-ithaca-ny",
    "patricia-and-philip-frost-art-museum-fiu-miami-fl": "the-patricia-phillip-frost-art-museum-miami-fl",
    "university-of-california-botanical-garden-at-berkeley-berkeley-ca": "uc-botanical-garden-at-berkeley-berkeley-ca",
    "utah-state-university-eastern-prehistoric-museum-price-ut": "usu-eastern-prehistoric-museum-price-ut",
    "the-louise-arnold-tanger-arboretum-at-lancasterhistory-lancaster-pa": "lancasterhistory-org-lancaster-pa",
    "eli-and-edythe-broad-museum-at-michigan-state-university-east-lansing-mi":
        "the-eli-and-edythe-broad-art-museum-east-lansing-mi",
    "milton-j-rubenstein-museum-of-science-technology-syracuse-ny": "museum-of-science-technology-most-syracuse-ny",
    "providence-athen-um-providence-ri": "providence-athenaeum-providence-ri",
    # Time Travelers listings of museums other programs already list (2026-09-23).
    "bob-bullock-texas-state-history-museum-austin-tx": "bullock-texas-state-history-museum-austin-tx",
    "friends-of-rancho-los-cerritos-long-beach-ca": "rancho-los-cerritos-long-beach-ca",
    "the-columbia-gorge-interpretive-center-museum-stevenson-wa": "columbia-gorge-museum-stevenson-wa",
    "connecticut-trolley-museum-east-windsor-ct": "ct-trolley-museum-east-windsor-ct",
    "old-davie-schhol-historical-museum-davie-fl": "old-davie-school-historical-museum-davie-fl",
    "freeborn-county-historical-society-albert-lea-mn": "history-center-of-freeborn-county-albert-lea-mn",
    "luxembourg-american-cultural-center-belgium-wi": "luxembourg-american-cultural-society-and-center-belgium-wi",
    "westford-historical-society-and-musem-westford-ma": "westford-museum-of-the-westford-historical-society-inc-westford-ma",
    "kemper-art-museum-saint-louis-mo": "mildred-lane-kemper-art-museum-st-louis-mo",   # ROAM lists it twice
    "lacawac-sanctuary-environmental-education-center-lake-ariel-pa": "lacawac-sanctuary-foundation-lake-ariel-pa",
    "union-county-heritage-museum-new-albany-ms":
        "the-william-faulkner-literary-garden-at-the-union-county-heritage-museum-new-albany-ms",
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


# Words too common to identify a museum on their own (checked after _GENERIC).
_WEAK = {"childrens", "children", "science", "sciences", "art", "arts", "history", "historical",
         "natural", "society", "garden", "gardens", "zoo", "aquarium", "university", "college",
         "county", "city", "state", "national", "house", "park", "institute"}
_ALT_SPLIT = re.compile(r"\s+\|\s+|\s*/\s*|\s+[–—-]\s+")


def _name_forms(name: str) -> List[List[str]]:
    """Word lists for each alternative form of a name: parentheticals dropped,
    split on " | ", "/" and " – " ("Shaker Museum | Mount Lebanon" -> both parts)."""
    base = re.sub(r"\([^)]*\)", " ", name)
    forms = []
    for part in [base] + _ALT_SPLIT.split(base):
        s = part.lower().replace("’", "'").replace("'s", "").replace("&", " and ")
        w = [("st" if x == "saint" else x) for x in re.findall(r"[a-z0-9]+", s)]
        w = [{"museums": "museum", "gardens": "garden"}.get(x, x) for x in w]
        while w and w[0] == "the":
            w = w[1:]
        while w and w[-1] in ("inc", "the"):
            w = w[:-1]
        if w:
            forms.append(w)
    return forms


def same_museum(a: str, b: str, city: Optional[str]) -> bool:
    """Do two names (same city + state, different programs) mean one museum?

    Yes if their distinctive words match ("Lindsay Wildlife Museum" /
    "Lindsay Wildlife Experience"), or if one form is a word-for-word prefix of
    the other and still has a distinctive word ("Wexner Center for the Arts" /
    "... at Ohio State University", "Newfields (Indianapolis Museum of Art)") or
    is 3+ words naming the place ("Wichita Art Museum" / "... and Art Garden").
    """
    core_a, core_b = _name_core(a, city), _name_core(b, city)
    if core_a and core_a == core_b:
        return True
    place = set(re.findall(r"[a-z0-9]+", (city or "").lower()))
    for fa in _name_forms(a):
        for fb in _name_forms(b):
            short, long_ = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
            if long_[:len(short)] != short:
                continue
            distinctive = any(w not in _GENERIC and w not in _WEAK and w not in place for w in short)
            # ...or the place itself is what identifies it: "Wichita Art Museum".
            placed = len(short) >= 3 and any(w in place for w in short)
            if distinctive or placed:
                return True
    return False


# Broad museum kinds for the app's "museum type" picker. A museum gets every kind
# its names match, plus its programs' own category (NARM/ROAM are mixed, so
# they add nothing). No match -> no kinds (the app files it under "Other").
KIND_PATTERNS = {
    "art": r"\bart(?!hur|illery)|galler|sculpture|contemporary|\bmoca\b|athen(a|æ)?eum|\bcraft|design|"
           r"photograph|glass|textile|decorative|painting|\bprints?\b|mural|architect",
    "children": r"children|\bkids?\b|youth|\bplay\b|playhouse|doseum",
    "science": r"scien|technolog|planetari|observatory|\bspace\b|aero|aviation|\bflight|\bair\b|"
               r"exploratorium|discovery (center|place|cube|world|park|lab)|innovation|engineer|\bstem\b|"
               r"\bsteam\b|invent|computer|energy|atomic",
    "history": r"(?<!natural )histor|heritage|pioneer|\bfort\b|house|homestead|mansion|plantation|village|"
               r"presidential|library|memorial|monument|battlefield|archive|genealog|railroad|railway|trolley|"
               r"maritime|military|veteran|\bwar\b|cabin|jail|lighthouse|hall of fame|\bfarm|\bmill\b|depot|"
               r"schoolhouse|cultur|\bnative\b|\bindian\b|tribal|pueblo|jewish|holocaust|african american|arab american|"
               r"chinese american|japanese american|mexican|latin[oa]|hispanic|irish|italian|german|polish|czech|"
               r"swedish|norwegian|asia|\bwest\b|western|cowboy|county museum|regional museum|state museum|"
               r"area museum|valley museum|automobile|\bauto\b|motor|wheels|clock|watch|\bski\b|industr|"
               r"precision|writers|music|\bblues\b|jazz|synagogue|sign museum|preservation",
    "nature": r"natural history|nature|wildlife|audubon|environment|ecolog|marine|ocean|preserve|geolog|"
              r"fossil|dinosaur|paleont|wetland|forest",
    "zoo": r"\bzoo|aquarium|aviary|safari|sea ?life|reptile|butterfly|raptor",
    "garden": r"garden|arboret|botanic|conservatory|horticult",
}
_KIND_RES = {k: re.compile(v, re.I) for k, v in KIND_PATTERNS.items()}
PROGRAM_KIND = {"ASTC": "science", "ACM": "children", "AZA": "zoo", "AHS": "garden", "TIMETRAVELERS": "history",
                "ANCA": "nature"}


def museum_kinds(names: List[str], programs) -> List[str]:
    """Kinds for a museum from all its names and its programs, in KIND_PATTERNS order."""
    text = " | ".join(names)
    found = {k for k, rx in _KIND_RES.items() if rx.search(text)}
    found |= {PROGRAM_KIND[p] for p in programs if p in PROGRAM_KIND}
    return [k for k in KIND_PATTERNS if k in found]


def clean_url(url: Optional[str]) -> Optional[str]:
    """A usable http(s) link or None: repairs "https:/x.com", adds a missing
    scheme, and drops placeholders like "http://Visit Site"."""
    if not url:
        return None
    u = re.sub(r"^(https?):/(?!/)", r"\1://", url.strip(), flags=re.I)
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u if re.match(r"^https?://[^\s/]+\.[a-z]{2,}(?::\d+)?(/\S*)?$", u, re.I) else None


def normalize_and_merge(records: List[Record]) -> List[dict]:
    """Merge records that describe the same physical museum into one record with
    a combined `programs` map. Keyed by slug(name, city, state); a record from
    another program also merges into a museum in the same city + state when
    `same_museum()` matches any name already merged there (programs often use
    old, short or suffixed names), or via SAME_MUSEUM. The first source's name
    and id win."""
    museums: Dict[str, dict] = {}
    by_place: Dict[object, List[str]] = {}  # normalized "city, st" -> museum ids there
    names: Dict[str, List[str]] = {}         # museum id -> every name merged into it
    today = date.today().isoformat()
    verified = today[:7]

    # Aliased listings go last: by then name matching has merged everything it
    # can, so an alias just joins its target (and can't block a same-program
    # listing of that museum from matching by name, e.g. ROAM's two Kempers).
    ordered = [r for r in records if r.id not in SAME_MUSEUM] + [r for r in records if r.id in SAME_MUSEUM]
    for r in ordered:
        key = SAME_MUSEUM.get(r.id, r.id)
        place = place_key(r.city, r.state) if r.city and r.state else (r.city, r.state)  # "Saint Louis" == "St. Louis"
        if key not in museums:
            for other in by_place.get(place, []):
                if r.program not in museums[other]["programs"] and \
                        any(same_museum(r.name, n, r.city) for n in names[other]):
                    key = other
                    break
        names.setdefault(key, [])
        if r.name not in names[key]:
            names[key].append(r.name)
        m = museums.get(key)
        if not m:
            by_place.setdefault(place, []).append(key)
            m = {
                "id": key, "name": r.name, "city": r.city, "state": r.state,
                "zip": r.zip, "country": r.country, "lat": r.lat, "lng": r.lng,
                "website": clean_url(r.website), "programs": {}, "sources": [], "last_seen": today,
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
        if r.tier is not None:
            entry["tier"] = r.tier
        if r.exclusion is not None:           # garden/museum opts into a distance rule
            entry["exclusion"] = r.exclusion
        prev = m["programs"].get(r.program)
        if prev:                              # same program lists this museum twice (aliases):
            if "exclusion" in entry and "exclusion" not in prev:
                prev["exclusion"] = entry["exclusion"]   # keep any distance rule either states
        else:
            m["programs"][r.program] = entry
        if r.source and r.source not in m["sources"]:
            m["sources"].append(r.source)
        if not m.get("zip") and r.zip:
            m["zip"] = r.zip
        if not m.get("website") and clean_url(r.website):
            m["website"] = clean_url(r.website)

    for key, m in museums.items():
        m["kinds"] = museum_kinds(names[key], m["programs"])
    return sorted(museums.values(), key=lambda x: x["id"])


# ---- Geocode (offline first, then cached Nominatim, bounded) ---------------
# Museums that arrive with coords (e.g. ACM) are left alone. The rest are placed
# at their ZIP centroid if the source gave a ZIP, else their CITY centroid from
# the Census place table — both offline (see geodata.py), and precise enough for
# the coarse 15-90 mile distance rules. Only cities missing from that table
# (townships, NYC boroughs, ...) hit Nominatim; those results are cached by
# "City, ST" in geocode_cache.json, which is committed, so each city is looked up
# once ever. The network step is strictly bounded (short timeout, per-run cap,
# polite delay) so it can never hang the CI job.
CACHE_PATH = HERE / "geocode_cache.json"
PLACES_PATH = HERE / "place_centroids.json"
# "City, ST" as sources print it, for locales no gazetteer or settlement search
# can place (hamlets, campuses, old spellings). Looked up by hand 2026-09-23.
GEO_OVERRIDES = {
    "St. Mary's City, MD": [38.180, -76.429],       # Historic St. Mary's City (not a Census place)
    "Colton's Point, MD": [38.225, -76.753],         # Census/OSM spell it "Coltons Point"
    "University Center, MI": [43.513, -83.962],      # Saginaw Valley State University campus
    "Bonito River, NM": [33.496, -105.523],          # NARM lists Fort Stanton by its river
    "Sanibel Island, FL": [26.449, -82.022],         # the city of Sanibel (mostly water, so no place point)
    "Staatsburgh, NY": [41.853, -73.920],            # the hamlet is "Staatsburg"
}
ZIPS_PATH = DATA / "zip_centroids.json"
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

    zips = _load_table(ZIPS_PATH)
    places = _load_table(PLACES_PATH)
    session = None
    new_lookups = 0
    updated = False
    for m in museums:
        if m.get("lat") is not None:          # already geocoded by its source
            continue
        pt = zips.get(m.get("zip") or "") or (
            places.get(place_key(m["city"], m["state"])) if m.get("city") and m.get("state") else None)
        pt = pt or GEO_OVERRIDES.get(_city_key(m) or "")
        if pt:
            m["lat"], m["lng"] = pt
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


def _load_table(path: Path) -> Dict[str, list]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


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
            # Structured, settlements only: a free-text "Harvard, MA" returns the university.
            params={"city": city_state.rsplit(", ", 1)[0], "state": city_state.rsplit(", ", 1)[-1],
                    "country": "USA", "featureType": "settlement", "format": "json", "limit": 1},
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
                    help="comma-separated: astc,acm,narm,roam,aza,ahs,timetravelers,anca")
    ap.add_argument("--from-fixtures", action="store_true",
                    help="use saved fixtures instead of live fetching (offline)")
    ap.add_argument("--no-geocode", action="store_true", help="skip network (Nominatim) geocoding; offline ZIP/place tables still apply")
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
