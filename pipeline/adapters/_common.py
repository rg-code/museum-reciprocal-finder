"""Shared types + helpers for source adapters.

Each adapter turns one association's published list into a list of `Record`s in
a common shape. Records are later normalized, geocoded, and merged (one museum
may appear in several programs) — see docs/ARCHITECTURE.md section 7.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# The app's seven in-scope networks.
NETWORKS = ["ASTC", "NARM", "ROAM", "AZA", "AHS", "TIMETRAVELERS", "ACM"]

_US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}
_STATE_ABBRS = set(_US_STATES.values())


def state_header(line: str) -> Optional[str]:
    """Return the 2-letter code if `line` is a state section header, else None."""
    key = line.strip().upper()
    if key in _US_STATES:
        return _US_STATES[key]
    if key in _STATE_ABBRS:
        return key
    return None


def slugify(*parts: Optional[str]) -> str:
    text = "-".join(p for p in parts if p)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


@dataclass
class Record:
    program: str                      # one of NETWORKS
    name: str
    city: Optional[str] = None
    state: Optional[str] = None       # 2-letter
    country: str = "US"
    benefit: Optional[str] = None     # None => use program default
    admits: Optional[int] = None      # None => use program default
    website: Optional[str] = None
    lat: Optional[float] = None       # set when the source already provides coords
    lng: Optional[float] = None
    source: str = ""                  # adapter tag, e.g. "astc"
    raw: str = ""                     # original line/snippet, for auditing

    @property
    def id(self) -> str:
        return slugify(self.name, self.city, self.state)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d
