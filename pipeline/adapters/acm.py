"""ACM Reciprocal Network adapter.

Source: findachildrensmuseum.org — museums flagged with the red "R" participate
in the Reciprocal Network (50% off admission, up to 6 people, no distance rule).

Design: `parse_html()` extracts reciprocal museums from the directory markup;
`fetch()` downloads the page and calls it. Only reciprocal-flagged entries are
kept. Tests run `parse_html()` against a saved fixture.

NOTE (Phase 0): confirm the live directory's markup and adjust the selectors.
Prefer a hidden JSON/XHR endpoint if the list is JS-rendered (see ARCHITECTURE 7.1).
"""
from __future__ import annotations

from typing import List

from _common import Record

ACM_DIRECTORY_URL = "https://findachildrensmuseum.org/reciprocal-network/"
SOURCE = "acm"
PROGRAM = "ACM"


def _truthy(val) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "y", "r")


def parse_html(html: str) -> List[Record]:
    """Extract reciprocal-flagged museums from the ACM directory HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: List[Record] = []

    for li in soup.select("li.museum"):
        # The red "R" flag marks reciprocal participants; skip the rest.
        if not _truthy(li.get("data-reciprocal", "")):
            continue

        name_el = li.select_one(".name")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name:
            continue

        city_el = li.select_one(".city")
        state_el = li.select_one(".state")
        website = name_el.get("href") or None
        state = state_el.get_text(strip=True).upper()[:2] if state_el else None

        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city_el.get_text(strip=True) if city_el else None,
                state=state,
                benefit="discount_50",  # ACM is uniformly 50% off
                admits=6,               # up to 6 people
                website=website,
                source=SOURCE,
                raw=li.get_text(" ", strip=True),
            )
        )
    return records


def fetch(session=None, url: str = ACM_DIRECTORY_URL) -> List[Record]:
    """Download the ACM directory and parse it into Records."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_html(resp.text)
