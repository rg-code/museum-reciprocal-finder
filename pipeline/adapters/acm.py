"""ACM Reciprocal Network adapter.

Source: findachildrensmuseum.org runs the Store Locator Plus plugin. Its
front-end AJAX endpoint (admin-ajax.php?action=csl_ajax_search) returns every
listed museum as JSON in a single request, including latitude/longitude and a
`category_names` field. Museums in the "Reciprocal" category are the ones with
the red "R" (50% off general admission, up to 6 people, no distance rule).

Verified against the live endpoint (Sep 2026): 384 total locations, 212 in the
Reciprocal category (210 in the US). Records arrive pre-geocoded, so the build
step does not need to geocode ACM entries.

US-only for v1: non-US countries (e.g. Canada) are dropped.
"""
from __future__ import annotations

import html
import json
from typing import List

from _common import Record, state_header

SOURCE = "acm"
PROGRAM = "ACM"
AJAX_URL = "https://findachildrensmuseum.org/wp-admin/admin-ajax.php"
# One broad search centered on the US with a huge radius returns the full list.
AJAX_BODY = "action=csl_ajax_search&radius=50000&address=USA&lat=39.5&lng=-98.35"


def _clean(s) -> str:
    return html.unescape(str(s or "")).strip()


def _to_float(v):
    try:
        return round(float(v), 5)
    except (TypeError, ValueError):
        return None


def parse_json(text: str) -> List[Record]:
    """Extract US 'Reciprocal' museums from the SLP AJAX JSON payload."""
    payload = json.loads(text)
    rows = payload.get("response") or payload.get("results") or []
    records: List[Record] = []

    for row in rows:
        cats = _clean(row.get("category_names")).lower()
        if "reciprocal" not in cats:
            continue
        country = _clean(row.get("country")).lower()
        if country and "united states" not in country:   # US-only for v1
            continue

        name = _clean(row.get("name"))
        if not name:
            continue

        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=_clean(row.get("city")) or None,
                state=state_header(_clean(row.get("state"))),  # full name -> 2-letter
                benefit="discount_50",   # ACM is uniformly 50% off
                admits=6,                # up to 6 people
                website=_clean(row.get("url")) or None,
                lat=_to_float(row.get("lat")),
                lng=_to_float(row.get("lng")),
                source=SOURCE,
                raw=f"{name} | {_clean(row.get('city'))}, {_clean(row.get('state'))}",
            )
        )
    return records


def fetch(session=None) -> List[Record]:
    """Query the SLP AJAX endpoint and parse the reciprocal museums."""
    import requests

    sess = session or requests.Session()
    resp = sess.post(
        AJAX_URL,
        data=AJAX_BODY,
        timeout=60,
        headers={
            "User-Agent": "museum-reciprocal-finder/0.2 (personal project)",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    resp.raise_for_status()
    return parse_json(resp.text)
