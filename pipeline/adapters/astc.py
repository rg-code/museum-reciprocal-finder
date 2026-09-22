"""ASTC Travel Passport adapter.

ASTC publishes an authoritative participant-list PDF (refreshed each May), e.g.
https://www.astc.org/wp-content/uploads/2026/04/Standard-List-11pt-Font.pdf

Design: `fetch()` downloads the PDF and extracts text; `parse_text()` turns that
text into Records. Tests exercise `parse_text()` against a saved fixture so we
never need the network or a real PDF to run them.

NOTE (Phase 0): confirm the exact PDF layout against the live file and tune the
line regex. The parser below targets the common "grouped by state" layout with
"Name, City, ST" entries and all-caps state section headers.
"""
from __future__ import annotations

from typing import List, Optional

from _common import Record, state_header

ASTC_LIST_URL = (
    "https://www.astc.org/wp-content/uploads/2026/04/Standard-List-11pt-Font.pdf"
)
SOURCE = "astc"
PROGRAM = "ASTC"

# Lines that are headers/footers, not institutions.
_SKIP_MARKERS = ("participant", "effective", "passport", "page ", "www.astc")


def _is_skippable(line: str) -> bool:
    low = line.lower()
    return not line or any(m in low for m in _SKIP_MARKERS)


def parse_text(text: str) -> List[Record]:
    """Parse ASTC PDF-extracted text into ASTC Records."""
    records: List[Record] = []
    current_state: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _is_skippable(line):
            continue

        st = state_header(line)
        if st:
            current_state = st
            continue

        name, city, state = _parse_entry(line, current_state)
        if not name:
            continue
        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city,
                state=state,
                benefit=None,   # program default: free
                source=SOURCE,
                raw=line,
            )
        )
    return records


def _parse_entry(line: str, current_state: Optional[str]):
    """Split 'Name, City, ST' / 'Name, City' / 'Name' (rsplit keeps commas in name)."""
    parts = [p.strip() for p in line.rsplit(",", 2)]
    if len(parts) == 3:
        name, city, state = parts
        state = state.split()[0].upper()[:2] if state else current_state
        return name, city or None, state or current_state
    if len(parts) == 2:
        name, city = parts
        return name, city or None, current_state
    return parts[0], None, current_state


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from the ASTC PDF (requires pdfplumber; only used by fetch())."""
    import io
    import pdfplumber  # imported lazily so tests don't need it

    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def fetch(session=None, url: str = ASTC_LIST_URL) -> List[Record]:
    """Download the ASTC participant PDF and parse it into Records."""
    import requests

    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_text(extract_pdf_text(resp.content))
