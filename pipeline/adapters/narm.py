"""NARM (North American Reciprocal Museum) adapter.

Source: narmassociation.org/members/ — a searchable HTML directory. All listed
institutions are members (no per-row flag). Benefit defaults to free; NARM's
per-institution proximity exclusion is left to the program default.

Design: `parse_html()` extracts member rows; `fetch()` downloads and calls it.
Tests run `parse_html()` against a saved fixture.

NOTE (Phase 0): the live directory may be JS-rendered/paginated — prefer a hidden
JSON/XHR endpoint if present (see ARCHITECTURE 7.1), then adjust selectors.
"""
from __future__ import annotations

from typing import List

from _common import Record

NARM_MEMBERS_URL = "https://narmassociation.org/members/"
SOURCE = "narm"
PROGRAM = "NARM"


def parse_html(html: str) -> List[Record]:
    """Extract member institutions from the NARM directory HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: List[Record] = []

    for row in soup.select("li.member, .member-row, tr.member"):
        name_el = row.select_one(".name, .member-name, a")
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
                benefit=None,          # program default: free
                website=website,
                source=SOURCE,
                raw=row.get_text(" ", strip=True),
            )
        )
    return records


def fetch(session=None, url: str = NARM_MEMBERS_URL) -> List[Record]:
    """Download the NARM members directory and parse it into Records."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_html(resp.text)
