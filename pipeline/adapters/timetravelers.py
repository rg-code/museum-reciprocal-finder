"""Time Travelers adapter (Missouri Historical Society's reciprocal program).

Source: the "List of Member Institutions" page on timetravelers.mohistory.org.
The site opts out of automated access (robots.txt is "Disallow: /" for every
agent), so the page is saved by hand from a browser into
pipeline/manual_drops/timetravelers/. build.py turns it into a same-named .txt
with `extract_html_text()` — only that .txt is committed — and parses it with
`parse_text()`.

Layout (verified on the page saved 2026-09-23, "Participating Institutions: 513
found"): a Vuetify list; each institution is an `a.v-list__tile--link` with a
title (name) and two sub-titles (one-line street address, website). Tiles
without sub-titles are the state picker and navigation. Addresses end in
"City, ST 12345" but vary: full state names ("Lodi, California 95240"),
missing commas ("Pensacola FL 32502"), trailing ", USA" or "(26 locations
statewide; call for details)", and two with no city at all (fixed below).

The list gives no per-institution benefit (free vs reduced admission is on each
institution's detail page), so benefit stays None -> program default "varies",
which the app shows as VERIFY.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from _common import Record, place_key, state_header

SOURCE = "timetravelers"
PROGRAM = "TIMETRAVELERS"
# Checked 2026-09-23: timetravelers.mohistory.org/robots.txt is 'Disallow: /'
# for all agents. We don't scrape sources that opt out, so this program is fed
# only by a manual drop.
BLOCKED_REASON = "timetravelers.mohistory.org/robots.txt is 'Disallow: /' for all agents"

HEADER = "Institution\tAddress\tWebsite"
# Addresses printed without a city/state. Name -> (city, state, zip).
_ADDRESS_FIXES = {
    "Lincoln Presidential Foundation": ("Springfield", "IL", "62704"),    # 944 Clock Tower Dr.
    "Johnson County Historical Society": ("Coralville", "IA", "52241"),   # 200 E. 9th St. (Iowa)
    "The Walt Disney Family Museum": ("San Francisco", "CA", "94129"),    # printed "The Presido San Fransico"
}
# Cities the list writes differently from the town's name.
_CITY_FIXES = {("Tampa Bay", "FL"): "Tampa",
               ("Ephralm", "WI"): "Ephraim"}   # Ephraim's Census point is null, so no ZIP check
PLACES_PATH = Path(__file__).resolve().parents[1] / "place_centroids.json"
ZIPS_PATH = Path(__file__).resolve().parents[2] / "data" / "zip_centroids.json"
_STREETISH = re.compile(r"^(st|street|ave|avenue|aveune|rd|road|dr|drive|blvd|boulevard|ln|lane|way|pkwy|"
                        r"parkway|hwy|highway|ct|court|pl|place|sq|square|trail|se|sw|ne|nw|box|ste|suite|"
                        r"#?\d+\w*)[.,]*$", re.I)
_geo: dict = {}


def _tables():
    """(places {"city, st": [lat,lng] | None}, zips {zip: [lat,lng]}, names by state)."""
    if not _geo:
        def load(path):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
        places, zips = load(PLACES_PATH), load(ZIPS_PATH)
        by_state: dict = {}
        for k in places:
            name, st = k.rsplit(", ", 1)
            by_state.setdefault(st, []).append(name)
        _geo.update(places=places, zips=zips, by_state=by_state)
    return _geo["places"], _geo["zips"], _geo["by_state"]


def _miles(a, b) -> float:
    from math import asin, cos, radians, sin, sqrt
    h = sin(radians(b[0] - a[0]) / 2) ** 2 + cos(radians(a[0])) * cos(radians(b[0])) * sin(radians(b[1] - a[1]) / 2) ** 2
    return 2 * 3958.8 * asin(sqrt(h))


def _display(key_name: str) -> str:
    """"st joseph" -> "St. Joseph" (for names taken from the place table)."""
    return " ".join("St." if w == "st" else w.capitalize() for w in key_name.split())


def _known_place(words: List[str], state: str) -> Optional[str]:
    """Longest run of trailing words that is a Census place/town in `state`."""
    places = _tables()[0]
    for n in range(min(4, len(words)), 0, -1):
        cand = " ".join(words[-n:])
        if place_key(cand, state) in places:
            return cand
    return None


def _near_zip(name: str, state: str, zip5: Optional[str], limit_mi: float) -> bool:
    places, zips, _ = _tables()
    pt, z = places.get(f"{name}, {state.lower()}"), zips.get(zip5 or "")
    return bool(pt and z and _miles(pt, z) <= limit_mi)


def _fuzzy_place(words: List[str], state: str, zip5: Optional[str]) -> Optional[str]:
    """Correct a misspelled town ("Lawerence", "St. Joesph") to a real one in the
    same state — only if that town is within 15 mi of the address's ZIP."""
    from rapidfuzz import fuzz, process

    names = _tables()[2].get(state.lower(), [])
    for n in range(min(3, len(words)), 0, -1):
        cand = place_key(" ".join(words[-n:]), state).rsplit(", ", 1)[0]
        if len(cand) < 5:
            continue
        cw = cand.split()
        # Fix the spelling of at most one word; never add, drop or swap words
        # ("Street Rancho Dominguez" must not become "East Rancho Dominguez").
        def one_typo(name: str) -> bool:
            nw = name.split()
            diff = [(a, b) for a, b in zip(cw, nw) if a != b]
            return len(nw) == len(cw) and len(diff) == 1 and fuzz.ratio(*diff[0]) >= 80
        hit = process.extractOne(cand, [x for x in names if one_typo(x)], scorer=fuzz.ratio, score_cutoff=85)
        if hit and _near_zip(hit[0], state, zip5, 15):
            return _display(hit[0])
    return None


def _nearest_place(state: str, zip5: Optional[str]) -> Optional[str]:
    """The town nearest the ZIP (within 10 mi), for addresses with no city."""
    places, zips, by_state = _tables()
    z = zips.get(zip5 or "")
    if not z:
        return None
    best = min(((_miles(p, z), n) for n in by_state.get(state.lower(), [])
                if (p := places.get(f"{n}, {state.lower()}"))), default=None)
    return _display(best[1]) if best and best[0] <= 10 else None


def extract_html_text(html: str) -> str:
    """Saved page -> tab-separated Institution, Address, Website (one per line)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tile in soup.select("a.v-list__tile--link"):
        title = tile.select_one(".v-list__tile__title")
        subs = [s.get_text(" ", strip=True) for s in tile.select(".v-list__tile__sub-title")]
        if not title or not subs:            # state picker / navigation entries
            continue
        cells = [title.get_text(" ", strip=True)] + subs[:2] + [""] * (2 - len(subs[:2]))
        rows.append("\t".join(c.replace("\t", " ") for c in cells))
    return "\n".join([HEADER] + rows) + "\n"


def _split_address(address: str):
    """One-line street address -> (city, 2-letter state, zip), or None if not US.

    Works back from the ZIP: the state is the last 3, 2 or 1 words ("District
    of Columbia", "West Virginia", "CA" — longest first). The city is what
    follows the last comma; when the street runs straight into the city
    ("5401 Woodward Avenue Detroit"), it's the longest trailing run of words
    that is a known place in that state. Misspelled towns are corrected only
    when the real town is within 15 mi of the address's ZIP; an address with no
    city takes the town nearest its ZIP; otherwise it's whatever follows the
    last street-ish word.
    """
    a = re.sub(r"\s*\([^)]*\)\s*$", "", address)          # "(3 locations; call for details)"
    a = re.sub(r"\.(?=[A-Z])", ". ", a)                   # "N Sixth St.Pheonix"
    a = re.sub(r",?\s*USA\s*$", "", a, flags=re.I)
    m = re.search(r"^(?P<rest>.*?)[,\s]+(?P<zip>\d{4,5})(?:-\d{4})?\s*$", a)
    if not m:
        return None                                        # no US ZIP (e.g. "Toronto ... M5V 3X5")
    words = m.group("rest").replace(",", " , ").split()
    for n in (3, 2, 1):
        tail = words[-n:]
        if len(words) > n and "," not in tail and state_header(" ".join(tail)):
            state, pre = state_header(" ".join(tail)), words[:-n]
            break
    else:
        return None
    while pre and pre[-1] == ",":
        pre = pre[:-1]
    seg = pre[len(pre) - pre[::-1].index(","):] if "," in pre else pre
    z = m.group("zip")
    zip5 = z if len(z) == 5 else None
    glued = re.match(r"^(.*[a-z])([A-Z][a-z]+)$", seg[-1]) if seg else None   # "WayBarre"
    city = (_known_place(seg, state)
            or (glued and _known_place(seg[:-1] + [glued.group(1), glued.group(2)], state))
            or _fuzzy_place(seg, state, zip5))
    if not city:
        if not seg or all(_STREETISH.match(w) for w in seg):   # "Wylie Dr, NE 68756": no city
            city = _nearest_place(state, zip5) or ""
        elif "," in pre:
            city = " ".join(seg)
        else:
            idx = max((i for i, w in enumerate(seg) if _STREETISH.match(w)), default=-1)
            city = " ".join(seg[idx + 1:])
            if not city:                          # only a street was given ("Wylie Dr")
                city = _nearest_place(state, zip5) or " ".join(seg[-1:])
    city = city.strip(" ,")
    return _CITY_FIXES.get((city, state), city), state, zip5


def parse_text(text: str) -> List[Record]:
    """Parse the tab-separated extract into US Time Travelers Records."""
    records: List[Record] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("Institution\t"):
            continue
        name, address, website = ((line.split("\t") + ["", ""])[:3])
        name, address, website = name.strip(), address.strip(), website.strip()
        loc = _ADDRESS_FIXES.get(name) or _split_address(address)
        if not name or not loc:              # non-US (e.g. TIFF, Toronto)
            continue
        city, state, zip5 = loc
        if website and not website.startswith("http"):
            website = "https://" + website
        records.append(Record(
            program=PROGRAM, name=name, city=city, state=state, zip=zip5,
            benefit=None,                    # program default "varies" -> VERIFY
            website=website or None, source=SOURCE, raw=f"{name} | {address}",
        ))
    return records


def fetch(session=None, url: str = "") -> List[Record]:
    """Not fetched automatically — the source opts out of automated access."""
    raise RuntimeError(
        f"Time Travelers is not scraped ({BLOCKED_REASON}). Save the 'List of Member "
        "Institutions' page from https://timetravelers.mohistory.org/ in a browser and put "
        "it in pipeline/manual_drops/timetravelers/ instead."
    )
