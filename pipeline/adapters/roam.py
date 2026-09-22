"""ROAM (Reciprocal Organization of Associated Museums) adapter.

Source: a PDF list grouped by state. Benefit is free; ROAM's 25-mile
inter-institution exclusion is the program default.

Design: `parse_text()` parses PDF-extracted text ("Name, City, ST" under all-caps
state headers); `fetch()` downloads + extracts + parses. Tests use a fixture.

NOTE (Phase 0): confirm the live PDF's column layout and tune the line parse.
"""
from __future__ import annotations

from typing import List, Optional

from _common import Record, state_header

SOURCE = "roam"
PROGRAM = "ROAM"

_SKIP_MARKERS = ("list of roam", "roam museums", "as of", "page ", "reciprocal")


def _is_skippable(line: str) -> bool:
    low = line.lower()
    return not line or any(m in low for m in _SKIP_MARKERS)


def parse_text(text: str) -> List[Record]:
    """Parse ROAM PDF-extracted text into ROAM Records."""
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

        parts = [p.strip() for p in line.rsplit(",", 2)]
        if len(parts) == 3:
            name, city, state = parts
            state = state.split()[0].upper()[:2] if state else current_state
        elif len(parts) == 2:
            name, city, state = parts[0], parts[1], current_state
        else:
            name, city, state = parts[0], None, current_state
        if not name:
            continue

        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city or None,
                state=state or current_state,
                benefit=None,      # program default: free
                source=SOURCE,
                raw=line,
            )
        )
    return records


def extract_pdf_text(pdf_bytes: bytes) -> str:
    import io
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def fetch(session=None, url: str = "") -> List[Record]:
    """Download the ROAM PDF and parse it. Pass the current PDF URL explicitly."""
    import requests

    if not url:
        raise ValueError("ROAM PDF URL required (list URL changes; pass url=...)")
    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_text(extract_pdf_text(resp.content))
