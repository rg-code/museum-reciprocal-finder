"""AHS (American Horticultural Society) Reciprocal Admissions Program adapter.

Source: the AHS garden network map, which loads a GeoJSON/JSON feed. Benefit is
free; the optional 90-mile residence exclusion is discretionary (program default,
not applied unless a garden opts in), matching AHS's "some gardens apply it" rule.

Design: `parse_json()` reads the feed (GeoJSON FeatureCollection or a plain list);
`fetch()` downloads + parses. Tests use a fixture.

NOTE (Phase 0): capture the real feed URL from the map's network calls and confirm
field names.
"""
from __future__ import annotations

import json
from typing import Any, List

from _common import Record

SOURCE = "ahs"
PROGRAM = "AHS"


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def parse_json(data: Any) -> List[Record]:
    """Parse an AHS feed (GeoJSON FeatureCollection or a list of gardens)."""
    if isinstance(data, str):
        data = json.loads(data)

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        items = [f.get("properties", {}) for f in data.get("features", [])]
    elif isinstance(data, dict) and "gardens" in data:
        items = data["gardens"]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    records: List[Record] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = _first(it, "name", "garden", "title")
        if not name:
            continue
        state = _first(it, "state", "st")
        records.append(
            Record(
                program=PROGRAM,
                name=str(name).strip(),
                city=(str(_first(it, "city", "town")).strip() if _first(it, "city", "town") else None),
                state=(str(state).strip().upper()[:2] if state else None),
                benefit=None,       # program default: free
                website=_first(it, "website", "url"),
                source=SOURCE,
                raw=json.dumps(it, sort_keys=True)[:300],
            )
        )
    return records


def fetch(session=None, url: str = "") -> List[Record]:
    """Download the AHS garden feed (JSON) and parse it. Pass the current feed URL."""
    import requests

    if not url:
        raise ValueError("AHS feed URL required (capture from the map; pass url=...)")
    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_json(resp.json())
