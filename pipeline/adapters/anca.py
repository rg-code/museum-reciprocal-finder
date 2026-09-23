"""ANCA (Association of Nature Center Administrators) Reciprocal Program adapter.

Source: natctr.org/membership/reciprocal-program — "Participating ANCA Members",
a plain HTML table on the page itself (robots.txt allows it; only system
folders are disallowed). Verified 2026-09-23: one <table>; a row whose first
cell holds an <h4> is a state heading ("Alabama" | "BACK TO TOP"); every other
row is <p><a href=site><strong>Name</strong></a></p><p><em>City</em></p> | benefit.
~158 organizations, all in the US.

Benefit is per organization, in free text ("Free Admission; 10% Store
Discount"), mapped conservatively:
- "Free Admission..." -> free ("Up to 5 people" -> admits 5)
- "50% Admission(s) Discount" -> discount_50; other N% -> discount_other
- "Free Admission with one paid adult admission" -> discount_other (2-for-1)
- seasonal ("...to Summer Adventure in June and July"), store / program /
  parking / lodging perks only, or "please contact" -> varies (VERIFY)
The page says "some organizations have certain exclusions ... if you live
within 50 miles" without saying which, so that's only applied where a row
states it ("excludes organizations within 50 miles").
"""
from __future__ import annotations

import re
from typing import List, Optional

from _common import Record, state_header

PAGE_URL = "https://natctr.org/membership/reciprocal-program"
SOURCE = "anca"
PROGRAM = "ANCA"
MIN_RECORDS = 60  # guardrail: the table lists ~158 organizations
# Cities the table writes differently from the town's name.
_CITY_FIXES = {("Salt Lake", "UT"): "Salt Lake City"}

_WITHIN_50 = re.compile(r"within\s+50\s+miles", re.I)
_ADMIT_PCT = re.compile(r"(\d+)\s*%\s*admissions?\s*discount", re.I)
_UP_TO = re.compile(r"up\s+to\s+(\d+)\s+people", re.I)
# "Free Admission" that isn't really general free entry.
_FREE_CONDITIONAL = re.compile(r"free admission\s+(to summer|with one paid)", re.I)


def _benefit(text: str):
    """Benefit text -> (benefit, admits, exclusion)."""
    t = " ".join(text.split())
    exclusion = {"radius_mi": 50, "anchors": ["home_institution"]} if _WITHIN_50.search(t) else None
    m = _UP_TO.search(t)
    admits = int(m.group(1)) if m else None
    if re.search(r"free admission with one paid", t, re.I):
        return "discount_other", admits, exclusion
    if re.search(r"free admission", t, re.I) and not _FREE_CONDITIONAL.search(t):
        return "free", admits, exclusion
    m = _ADMIT_PCT.search(t)
    if m:
        return ("discount_50" if int(m.group(1)) == 50 else "discount_other"), admits, exclusion
    return "varies", admits, exclusion


def parse_html(html: str) -> List[Record]:
    """Parse the reciprocal-program page (or just its table) into ANCA Records."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: List[Record] = []
    state: Optional[str] = None
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        heading = cells[0].find("h4")
        if heading:                                   # state heading row
            state = state_header(heading.get_text(" ", strip=True).replace("\xa0", " "))
            continue
        if cells[0].find("h3"):                       # "Organization & Location" header
            continue
        name_el = cells[0].find("strong")
        name = " ".join(name_el.get_text(" ", strip=True).split()) if name_el else ""
        city_el = cells[0].find("em")
        city = " ".join(city_el.get_text(" ", strip=True).split()) if city_el else None
        link = cells[0].find("a", href=True)
        text = " ".join(cells[1].get_text(" ", strip=True).replace("\xa0", " ").split())
        if not name or not state:
            continue
        city = _CITY_FIXES.get((city, state), city)
        benefit, admits, exclusion = _benefit(text)
        records.append(Record(
            program=PROGRAM, name=name, city=city, state=state,
            benefit=benefit, admits=admits, exclusion=exclusion,
            website=link["href"] if link else None,
            source=SOURCE, raw=f"{name} | {city} | {text}"[:300],
        ))
    return records


def fetch(session=None) -> List[Record]:
    """Download the reciprocal-program page and parse its member table."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(PAGE_URL, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.2 (personal project)"})
    resp.raise_for_status()
    records = parse_html(resp.text)
    if len(records) < MIN_RECORDS:   # the table moved or changed shape: fail loudly, don't publish a stub
        raise ValueError(f"ANCA page parsed to only {len(records)} organizations — layout changed?")
    return records
