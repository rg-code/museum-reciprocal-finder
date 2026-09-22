"""Time Travelers adapter.

Source: timetravelers.mohistory.org — an HTML directory of historical museums/sites.
Benefit is set per institution (free or reduced), so the adapter leaves benefit as
the program default ("varies"), which the UI shows as "verify" until confirmed.

Design: `parse_html()` extracts member rows; `fetch()` downloads + parses.
Tests run `parse_html()` against a saved fixture.

NOTE (Phase 0): confirm the live markup; the directory may be paginated by state.
"""
from __future__ import annotations

from typing import List

from _common import Record

TIMETRAVELERS_URL = "https://timetravelers.mohistory.org/"
SOURCE = "timetravelers"
PROGRAM = "TIMETRAVELERS"


def parse_html(html: str) -> List[Record]:
    """Extract Time Travelers member institutions from the directory HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: List[Record] = []

    for row in soup.select("li.member, .institution, tr.member"):
        name_el = row.select_one(".name, .institution-name, a")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name:
            continue
        city_el = row.select_one(".city")
        state_el = row.select_one(".state")
        website = name_el.get("href") if name_el.name == "a" else None

        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city_el.get_text(strip=True) if city_el else None,
                state=(state_el.get_text(strip=True).upper()[:2] if state_el else None),
                benefit=None,       # program default: "varies" -> UI shows "verify"
                website=website,
                source=SOURCE,
                raw=row.get_text(" ", strip=True),
            )
        )
    return records


def fetch(session=None, url: str = TIMETRAVELERS_URL) -> List[Record]:
    """Download the Time Travelers directory and parse it into Records."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_html(resp.text)
