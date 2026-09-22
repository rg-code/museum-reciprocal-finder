"""AZA (Association of Zoos & Aquariums) reciprocal adapter.

Source: an annual PDF (May-April) at aza.org/reciprocity. Benefit is set PER
institution (typically 50% off, sometimes free/100%), so the adapter reads the
discount column and maps it to a benefit; unknown -> program default (discount_50).

Design: `parse_text()` handles "Name, City, ST - <discount>" style lines;
`fetch()` downloads + extracts + parses. Tests use a fixture.

NOTE (Phase 0): confirm the live PDF's columns (name / location / discount) and
tune the discount detection.
"""
from __future__ import annotations

import re
from typing import List, Optional

from _common import Record, state_header

SOURCE = "aza"
PROGRAM = "AZA"

_SKIP_MARKERS = ("reciprocity", "reciprocal list", "effective", "page ", "association of zoos")


def _is_skippable(line: str) -> bool:
    low = line.lower()
    return not line or any(m in low for m in _SKIP_MARKERS)


def _benefit_from(text: str) -> Optional[str]:
    """Map a discount snippet to a benefit. None => program default (discount_50)."""
    low = text.lower()
    if "free" in low or "100%" in low or "no charge" in low:
        return "free"
    if "50%" in low or "50 %" in low or "half" in low:
        return "discount_50"
    m = re.search(r"(\d{1,3})\s*%", low)
    if m:
        pct = int(m.group(1))
        if pct >= 100:
            return "free"
        return "discount_50" if pct == 50 else "discount_other"
    return None


def parse_text(text: str) -> List[Record]:
    """Parse AZA PDF-extracted text into AZA Records."""
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

        # Split an optional trailing discount after a dash/pipe/tab.
        location_part, discount_part = line, ""
        m = re.split(r"\s+[-–—|]\s+", line, maxsplit=1)
        if len(m) == 2:
            location_part, discount_part = m[0].strip(), m[1].strip()

        parts = [p.strip() for p in location_part.rsplit(",", 2)]
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
                benefit=_benefit_from(discount_part),  # None => default discount_50
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
    """Download the AZA reciprocity PDF and parse it. Pass the current PDF URL."""
    import requests

    if not url:
        raise ValueError("AZA PDF URL required (annual list URL changes; pass url=...)")
    sess = session or requests.Session()
    resp = sess.get(url, timeout=60, headers={"User-Agent": "museum-reciprocal-finder/0.1"})
    resp.raise_for_status()
    return parse_text(extract_pdf_text(resp.content))
