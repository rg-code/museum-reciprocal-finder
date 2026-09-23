"""AHS (American Horticultural Society) Garden Network / Reciprocal Admissions adapter.

Source: https://ahsgardening.org/ahs-garden-network/ . The map on that page is
drawn by the theme's custom-scripts.js from an inline WordPress-localized
variable, `var js_data = {"locations": "<JSON string>", ...}`, embedded in the
page HTML itself (there is no separate feed endpoint; the theme's admin-ajax
calls are only a geocode cache for the search box). So one GET of the page
returns every garden: `name`, `position` {lat, lng}, and an HTML `description`
holding the street address, "City, State ZIP" line, phone, a "Visit Site" link,
an optional "Additional Benefits:" list (gift-shop discounts etc. -- extras on
top of free admission) and an optional "To Note:" line (e.g. "Local Visitor
Exception" = the garden applies the 90-mile rule, "By Reservation Only",
"Parking Fee", or a genuinely reduced benefit such as a 50% discount).

Verified against the live page (Sep 2026): 401 locations, 391 in the US
(50 states + DC + PR); Canada, the UK, Cayman Islands and the US Virgin Islands
are dropped. Coordinates come with the feed, so AHS records need no geocoding.

Benefit: None (program default: free) unless the "To Note" text says the garden
gives only a discount ("50% discount" -> discount_50; other % / discounted
admission -> discount_other). An explicit admit count ("two free admissions")
sets `admits`. Other notes are kept in `raw` for auditing.

Design: `parse_json()` (pure, offline) accepts the page HTML, the js_data
object, or the locations list; `fetch()` downloads the page and parses it.
robots.txt allows all paths (Crawl-delay: 10); this adapter makes one request.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any, List, Optional

from _common import Record, state_header

SOURCE = "ahs"
PROGRAM = "AHS"
PAGE_URL = "https://ahsgardening.org/ahs-garden-network/"
USER_AGENT = "museum-reciprocal-finder/0.2 (personal project)"

_JS_DATA = re.compile(r"var\s+js_data\s*=\s*(\{.*?\})\s*;\s*(?:\n|//|</script>)", re.S)
# "Ridgely, Maryland 21660" / "Avalon, CA  90704" / "Washington, D.C. 20008-1234"
_CITY_ST_ZIP = re.compile(
    r"^(?P<city>.+),\s*(?P<st>[A-Za-z][A-Za-z .’'ʻ]*?)\.?,?\s+(?P<zip>\d{5})(?:-\d{4})?\b")
_PCT = re.compile(r"(\d{1,3})\s*%\s*(?:discount|off)", re.I)
_DISCOUNT_ADMISSION = re.compile(r"discount(?:ed)?\s+(?:general\s+)?admission|admission\s+discount", re.I)
_LOCAL_VISITOR = re.compile(r"local\s+visitor\s+exception", re.I)
LOCAL_VISITOR_EXCLUSION = {"radius_mi": 90, "anchors": ["residence"]}
_ADMITS = re.compile(
    r"\b(one|two|three|four|five|six|\d)\s+(?:free\s+|complimentary\s+)?"
    r"(?:admissions|admits|guests|people|persons|visitors)\b", re.I)
_NOT_PARTICIPATING = re.compile(r"not\s+(?:currently\s+)?participat|no\s+longer\s+participat", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _clean(s: Any) -> str:
    """Unescape entities, turn NBSPs into spaces, collapse whitespace."""
    s = html.unescape(str(s or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _to_float(v) -> Optional[float]:
    try:
        f = round(float(v), 5)
    except (TypeError, ValueError):
        return None
    return f if f else None


def _blocks(desc: str) -> List[List[str]]:
    """Description HTML -> paragraphs (blocks) of cleaned, non-empty lines."""
    t = re.sub(r"\s+", " ", desc)            # source newlines are not line breaks
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(?:p|div|li|h\d)\s*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    out: List[List[str]] = []
    for para in re.split(r"\n\s*\n", t):
        lines = [_clean(x) for x in para.split("\n")]
        lines = [x for x in lines if x]
        if lines:
            out.append(lines)
    return out


def _address(lines: List[str]):
    """First "City, State ZIP" line whose state is a US state/DC/PR."""
    for line in lines:
        m = _CITY_ST_ZIP.match(line)
        if not m:
            continue
        st = state_header(m.group("st").replace(".", ""))
        if st:
            return m.group("city").strip(), st, m.group("zip")
    return None


def _website(desc: str) -> Optional[str]:
    links = re.findall(r'<a\b[^>]*?\bhref\s*=\s*"([^"]+)"[^>]*>(.*?)</a>', desc, re.S | re.I)
    ext = [(h.strip(), _clean(re.sub(r"<[^>]+>", "", txt))) for h, txt in links
           if h.strip().lower().startswith("http") and "ahsgardening.org" not in h.lower()]
    for href, txt in ext:
        if "visit site" in txt.lower():
            return html.unescape(href)
    return html.unescape(ext[0][0]) if ext else None


def _note(blocks: List[List[str]]) -> str:
    """Text of the "To Note:" section (to the end of its paragraph)."""
    for n, b in enumerate(blocks):
        text = " ".join(b)
        i = text.lower().find("to note")
        if i >= 0:
            note = text[i + len("to note"):].lstrip(" :").strip()
            if not note and n + 1 < len(blocks):   # "To Note:" alone in its paragraph
                note = " ".join(blocks[n + 1])
            return note
    return ""


def _benefit_admits(terms: str):
    benefit = None
    m = _PCT.search(terms)
    if m:
        benefit = "discount_50" if int(m.group(1)) == 50 else "discount_other"
    elif _DISCOUNT_ADMISSION.search(terms):
        benefit = "discount_other"
    admits = None
    m = _ADMITS.search(terms)
    if m:
        w = m.group(1).lower()
        admits = _WORDNUM.get(w) or int(w)
    return benefit, admits


def extract_locations(page_html: str) -> List[dict]:
    """Pull the `js_data.locations` list out of the garden-network page HTML."""
    m = _JS_DATA.search(page_html)
    if not m:
        raise ValueError("AHS page has no `var js_data = {...}` map data (layout changed?)")
    return _locations_from(json.loads(m.group(1)))


def _locations_from(data: Any) -> List[dict]:
    if isinstance(data, dict) and "locations" in data:
        data = data["locations"]
        if isinstance(data, str):          # WP localizes it as a JSON string
            data = json.loads(data)
    return data if isinstance(data, list) else []


def parse_json(data: Any) -> List[Record]:
    """Parse AHS gardens into US Records.

    `data` may be the garden-network page HTML, the `js_data` object (dict or
    JSON text), or the locations list itself (list or JSON text).
    """
    if isinstance(data, str):
        s = data.lstrip()
        data = extract_locations(data) if s.startswith("<") else json.loads(s)
    items = _locations_from(data)

    records: List[Record] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = _clean(it.get("name"))
        if not name:
            continue
        desc = str(it.get("description") or "")
        blocks = _blocks(desc)
        lines = [x for b in blocks for x in b]
        addr = _address(lines)
        if not addr:            # non-US (Canada, UK, Cayman, USVI) or no address
            continue
        city, state, zip5 = addr

        note = _note(blocks)
        terms = " ".join([note] + [x for x in lines if "reciprocal" in x.lower()])
        if _NOT_PARTICIPATING.search(terms):
            continue
        benefit, admits = _benefit_admits(terms)
        # "Local Visitor Exception": this garden applies AHS's optional 90-mile rule
        # (no free entry if you live within 90 mi), so record it as opted in.
        exclusion = LOCAL_VISITOR_EXCLUSION if _LOCAL_VISITOR.search(terms) else None

        pos = it.get("position") or {}
        raw = f"{name} | {city}, {state} {zip5}" + (f" | To Note: {note}" if note else "")
        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city,
                state=state,
                benefit=benefit,        # None => program default (free)
                admits=admits,
                exclusion=exclusion,
                website=_website(desc),
                zip=zip5,
                lat=_to_float(pos.get("lat")),
                lng=_to_float(pos.get("lng")),
                source=SOURCE,
                raw=raw[:300],
            )
        )
    return records


def fetch(session=None) -> List[Record]:
    """Download the AHS garden-network page (one request) and parse its map data."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(PAGE_URL, timeout=60, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    records = parse_json(resp.text)
    if not records:
        raise ValueError("AHS page parsed to 0 US gardens (layout changed?)")
    return records
