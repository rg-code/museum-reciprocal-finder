"""ASTC Travel Passport adapter.

ASTC publishes the participant list as a PDF. We use the compact **2-page
abridged summary** (grouped by state), which is the cleanest bulk source:
each institution is one row of "Name, City (phone) [ID Required]" under an
ALL-CAPS state/country header. The 33- and 53-page variants add per-venue
membership-tier prose that is not worth parsing.

Verified against the live file (Sep 2026): the abridged PDF is a 3-column
landscape layout, ~348 US institutions. `fetch()` discovers the current
abridged URL from the passport page, downloads it, and reconstructs the
columns into one normalized line per row; `parse_text()` turns those lines
into Records and is exercised offline against a saved fixture.

US-only for v1: rows under non-US headers (CANADA, AUSTRALIA, ...) and the
preamble box (EXCLUSION, BEFORE YOU TRAVEL ...) are skipped because their
"state" is not a recognized US state.
"""
from __future__ import annotations

import re
from typing import List, Optional

from _common import Record, state_header

PASSPORT_PAGE = "https://www.astc.org/passport/"
# Fallback if the passport page can't be scraped for the current link.
ASTC_ABRIDGED_FALLBACK = (
    "https://www.astc.org/wp-content/uploads/2026/04/Abridged-List-2-Page-Summary.pdf"
)
SOURCE = "astc"
PROGRAM = "ASTC"

# A US phone anywhere in the tail: "(256) 237-6766", "256 237 6766", "707) 826-4480".
_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}")


def parse_text(text: str) -> List[Record]:
    """Parse the reconstructed abridged-list text into ASTC Records.

    Input is one item per line: either an ALL-CAPS section header or a
    "Name, City <phone> [ID Required]" institution row.
    """
    records: List[Record] = []
    current_state: Optional[str] = None  # 2-letter, or None under a non-US header

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        st = state_header(line)
        if st:                       # a recognized US state header
            current_state = st
            continue
        if _is_section_header(line):  # non-US country / preamble section heading
            current_state = None
            continue
        if current_state is None or "," not in line:
            continue                 # stray fragment, or data under a non-US header

        name, city = _split_name_city(line)
        if not name:
            continue
        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city,
                state=current_state,
                benefit=None,         # program default: free
                source=SOURCE,
                raw=line,
            )
        )
    return records


def _is_section_header(line: str) -> bool:
    """An ALL-CAPS heading (state/country/section name) with no comma.

    Used to reset scope at non-US sections (CANADA, AUSTRALIA, EXCLUSION, ...).
    Museum rows always contain a comma, so they never match here — and a stray
    mixed-case fragment is skipped WITHOUT resetting state, so it can't cascade-
    drop the rest of a section.
    """
    return (
        "," not in line
        and len(line) <= 40
        and any(c.isalpha() for c in line)
        and line == line.upper()
    )


def _split_name_city(line: str):
    """"Name, City (phone) [ID Required]" -> (name, city).

    The name itself can contain commas, so the city is the LAST comma-field
    once the phone number and the "ID Required" marker are stripped.
    """
    s = _PHONE.split(line, maxsplit=1)[0]          # drop phone and everything after
    s = re.sub(r"ID\s*Required", "", s, flags=re.I)
    s = s.strip().rstrip(" ,(-").strip()
    name, sep, city = s.rpartition(",")
    if not sep:                                    # no comma left -> all name
        return s.strip(), None
    return name.strip(), (city.strip() or None)


# ---- Live fetch (network + PDF; not exercised by unit tests) ----------------
def _discover_abridged_url(html: str) -> Optional[str]:
    m = re.search(r'href="([^"]*Abridged[^"]*\.pdf)"', html, flags=re.I)
    return m.group(1) if m else None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Reconstruct the abridged PDF into one normalized line per row.

    The layout is 3 columns; naive full-page extraction interleaves them. Rather
    than cluster words by hand (fragile — per-glyph `top` varies within a row),
    we crop each column band and let pdfplumber do its own line grouping, which
    keeps every "Name, City <phone>" row intact. Columns start near x≈18/274/529
    on the 792pt-wide page, so band cuts at ~1/3 and ~2/3 fall in the gutters.
    """
    import io
    import pdfplumber  # imported lazily so unit tests don't need it

    lines: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            width, height = float(page.width), float(page.height)
            bands = [(0.0, width * 0.334), (width * 0.334, width * 0.657), (width * 0.657, width)]
            for x0, x1 in bands:
                col = page.crop((x0, 0, x1, height))
                text = col.extract_text(x_tolerance=1, y_tolerance=3) or ""
                for raw in text.split("\n"):
                    line = raw.strip()
                    if line:
                        lines.append(line)
    return "\n".join(lines)


def fetch(session=None) -> List[Record]:
    """Download the current abridged participant PDF and parse it."""
    import requests

    sess = session or requests.Session()
    headers = {"User-Agent": "museum-reciprocal-finder/0.2 (personal project)"}
    url = ASTC_ABRIDGED_FALLBACK
    try:
        page = sess.get(PASSPORT_PAGE, timeout=30, headers=headers)
        page.raise_for_status()
        found = _discover_abridged_url(page.text)
        if found:
            url = found
    except Exception:  # noqa: BLE001 - fall back to the known URL
        pass

    resp = sess.get(url, timeout=60, headers=headers)
    resp.raise_for_status()
    return parse_text(extract_pdf_text(resp.content))
