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


# Checked 2026-09-23: timetravelers.mohistory.org/robots.txt is 'Disallow: /' for all agents. We don't scrape sources that opt out, so this
# program is fed only by a manual drop (pipeline/manual_drops/timetravelers/).
BLOCKED_REASON = "timetravelers.mohistory.org/robots.txt is 'Disallow: /' for all agents"


def fetch(session=None, url: str = "") -> List[Record]:
    """Not fetched automatically — the source opts out of automated access."""
    raise RuntimeError(
        f"Time Travelers is not scraped ({BLOCKED_REASON}). Put a saved copy of the participant directory (or a list from the Missouri Historical Society) in "
        "pipeline/manual_drops/timetravelers/ instead."
    )
