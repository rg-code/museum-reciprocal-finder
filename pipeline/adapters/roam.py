"""ROAM (Reciprocal Organization of Associated Museums) adapter.

Source: ROAM's Google Site (https://sites.google.com/site/roammuseums/home)
links "List of Participating ROAM Museums" to a PDF on Google Drive, e.g.
"ROAM Museums - September 2026 Website Listing.pdf". ROAM re-uploads it every
few months under a NEW Drive file id, so `fetch()` scrapes the current id from
the site and falls back to the last known id (then to a museum-hosted mirror).

The PDF is a print of a Google Sheet: one table, five columns
    State | City | Museum | Restrictions | Restriction Details
repeated on every page under a title + legend block. Restrictions are symbols:
    *  may be restricted for concerts/lectures/special exhibitions/ticketed events
    +  25-mile (40 km) exclusion between member institutions (program default)
    ‡  does not apply to [Restriction Details]
None of these change the benefit (free admission), so `benefit` stays None.
"+" is per-institution (only ~1 in 5 rows carry it), so rows marked "+" get
`exclusion=INTER_INSTITUTION_EXCLUSION` (like AHS's opt-in rule); unmarked rows
leave `exclusion` None. The symbols and details are kept in `raw` for auditing.

Verified against the live layout (Sep 2026; March-2026 file, 13 pages, ~700
rows, ~600 US). Quirks handled:
  * The State column is narrow and CLIPS long names: "North Carolin",
    "District of Co", "Massachusett", plus the typo "Massachusse". We resolve
    them by unique prefix (then a strict fuzzy prefix match).
  * Clipped glyphs that straddle the cell border ("tt" ligature of
    "Massachusetts") land in the City cell with naive table extraction
    ("ttBoston"); we assign each glyph to the cell its left edge is in.
  * Long names/cities wrap inside the cell; wrapped lines are re-joined.
  * Older files used 2-letter state codes and "United States"/"Canada" rows;
    both forms parse.
Non-US rows (Online, Canadian provinces, Colombia, Panamá, England, ...) are
dropped: their "state" is not a US state/DC/PR. The source gives no ZIP,
coordinates, website, or admit count.

Design: `extract_pdf_text()` turns the PDF into one tab-separated line per
table row; `parse_text()` (pure, offline-tested) turns those lines into
Records. `parse_text()` also accepts a CSV export of the sheet (manual drop).
"""
from __future__ import annotations

import csv
import difflib
import re
import sys
from typing import List, Optional, Sequence, Tuple

from _common import Record, state_header, _US_STATES

SITE_PAGES = (
    "https://sites.google.com/site/roammuseums/home",
    "https://sites.google.com/site/roammuseums/home/information-for-current-roam-museums",
)
# Last known list (Sep 2026: "ROAM Museums - September 2026 Website Listing.pdf").
ROAM_DRIVE_ID_FALLBACK = "1lam68fgSi2MxRhZtIywp2oq_skfu62Xa"
DRIVE_DOWNLOAD = "https://drive.google.com/uc?export=download&id={id}"
# Last resort if Google Drive is unreachable: a member museum's copy of an
# earlier listing (same layout; may be months stale — a warning is printed).
MIRROR_FALLBACKS = (
    "https://mocadetroit.org/wp-content/uploads/2026/04/ROAM-Museums-March-2026-Website-Listing.pdf",
)
USER_AGENT = "museum-reciprocal-finder/0.2 (personal project)"
# Set on rows marked "+" (the institution enforces ROAM's 25-mile rule).
INTER_INSTITUTION_EXCLUSION = {"radius_mi": 25, "anchors": ["inter_institution"]}
MIN_RECORDS = 50  # a real list has ~600 US rows; fewer means we grabbed the wrong file

SOURCE = "roam"
PROGRAM = "ROAM"

# Rows that are layout, not museums.
_HEADER_CELLS = {"state", "state full", "city", "museum", "restrictions", "restriction details"}
_RESTRICTION_SYMBOLS = "*+‡†"
# Cities the sheet gets wrong. Keyed by (city as printed, state) -> real city.
_CITY_FIXES = {
    ("Laurel Hill Cemetery", "PA"): "Philadelphia",
    ("Fon du Lac", "WI"): "Fond du Lac",
}
# Rows filed under the wrong state. (name, city, state as printed) -> real state.
_STATE_FIXES = {
    ("Swift County Historical Society", "Benson", "MI"): "MN",
    ("National Corvette Museum", "Bowling Green", "KS"): "KY",
}


def parse_text(text: str) -> List[Record]:
    """Parse extracted ROAM rows (tab-separated, or CSV) into US ROAM Records.

    Each museum row is State, City, Museum[, Restrictions[, Details]]. Title,
    legend, header, country-heading, and non-US rows are skipped.
    """
    records: List[Record] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        cells = _split_row(raw_line)
        if len(cells) < 3:
            continue
        state_raw, city, name = cells[0], cells[1], cells[2]
        restrictions = cells[3] if len(cells) > 3 else ""
        details = cells[4] if len(cells) > 4 else ""
        if not name or name.lower() in _HEADER_CELLS or state_raw.lower() in _HEADER_CELLS:
            continue
        state = resolve_state(state_raw)
        if not state:
            continue  # non-US (province/country/"Online") or not a data row
        name = _clean_name(name)
        city = city or None
        state = _STATE_FIXES.get((name, city, state), state)
        if city:
            city = _CITY_FIXES.get((city, state), city)
        if not name:
            continue
        raw = " | ".join(c for c in (state_raw, cells[1], cells[2], restrictions, details) if c)
        records.append(
            Record(
                program=PROGRAM,
                name=name,
                city=city,
                state=state,
                benefit=None,  # program default: free (restrictions don't change it)
                exclusion=dict(INTER_INSTITUTION_EXCLUSION) if "+" in restrictions else None,
                source=SOURCE,
                raw=raw[:240],
            )
        )
    return records


def _split_row(line: str) -> List[str]:
    if "\t" in line:
        cells = line.split("\t")
    else:
        cells = next(csv.reader([line]), [])
    return [_ws(c) for c in cells]


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()  # \s also matches NBSP


def _clean_name(name: str) -> str:
    # Restriction markers belong in their own column; strip any that leaked.
    name = name.rstrip(" " + _RESTRICTION_SYMBOLS).strip()
    return name.strip(" ,;")


def resolve_state(value: str) -> Optional[str]:
    """US state/DC/PR name, 2-letter code, or CLIPPED name -> 2-letter code.

    "North Carolin" -> NC, "District of Co" -> DC, "Massachusse" -> MA
    (clipped + misspelled). Provinces/countries/"Online" -> None.
    """
    s = _ws(value).rstrip(".")
    if not s:
        return None
    code = state_header(s)
    if code:
        return code
    key = s.upper()
    if len(key) < 4:
        return None
    prefixed = {c for n, c in _US_STATES.items() if n.startswith(key)}
    if len(prefixed) == 1:
        return prefixed.pop()
    if len(key) >= 8:  # clipped AND misspelled; be strict so provinces never match
        scored = sorted(
            ((difflib.SequenceMatcher(None, key, n[: len(key)]).ratio(), c)
             for n, c in _US_STATES.items()),
            reverse=True,
        )
        if scored[0][0] >= 0.85 and scored[0][0] - scored[1][0] > 0.1:
            return scored[0][1]
    return None


# ---- PDF -> rows (needs pdfplumber; exercised live, and via _cells_text) ----
Cell = Optional[Tuple[float, float, float, float]]  # (x0, top, x1, bottom) or None if merged


def _cells_text(cells: Sequence[Cell], chars: Sequence[dict]) -> List[str]:
    """Text of each cell in one table row.

    A glyph belongs to the cell containing its LEFT edge (+0.5pt slack). This
    matters because the sheet clips overflowing State text at the border, and
    a glyph cut there (e.g. the "tt" ligature at the end of "Massachuse-tts")
    straddles into the City cell; center/overlap assignment would glue it
    onto the city ("ttBoston"). Wrapped lines inside a cell are re-joined.
    """
    from pdfplumber.utils import extract_text

    live = [(i, c) for i, c in enumerate(cells) if c is not None]
    buckets: List[List[dict]] = [[] for _ in cells]
    if not live:
        return ["" for _ in cells]
    top = min(c[1] for _, c in live)
    bottom = max(c[3] for _, c in live)
    for ch in chars:
        mid = (ch["top"] + ch["bottom"]) / 2
        if not (top <= mid <= bottom):
            continue
        x = ch["x0"] + 0.5
        owner = None
        for i, c in live:
            if c[0] <= x:
                owner = i          # last cell starting left of the glyph
        if owner is not None and x <= cells[owner][2] + 0.5:
            buckets[owner].append(ch)
    out = []
    for b in buckets:
        txt = extract_text(b, x_tolerance=1.5, y_tolerance=3) if b else ""
        out.append(_ws(txt))
    return out


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Reconstruct the ROAM PDF into one tab-separated line per table row."""
    import io
    import pdfplumber  # imported lazily so unit tests don't need it

    lines: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            chars = page.chars
            for table in page.find_tables():
                for row in table.rows:
                    cells = _cells_text(row.cells, chars)
                    if any(cells):
                        lines.append("\t".join(cells))
    return "\n".join(lines)


# ---- Live fetch (network + PDF; not exercised by unit tests) ----------------
_DRIVE_ID = re.compile(
    r"(?:drive|docs)\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^\"'\s]*?&(?:amp;)?)?id=)([A-Za-z0-9_-]{20,})"
)


def _discover_drive_ids(html: str) -> List[str]:
    """Drive file ids linked from a ROAM site page, in page order."""
    seen: List[str] = []
    for m in _DRIVE_ID.finditer(html):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _download_pdf(sess, url: str, headers: dict) -> bytes:
    resp = sess.get(url, timeout=60, headers=headers)
    resp.raise_for_status()
    if resp.content[:5] == b"%PDF-":
        return resp.content
    # Drive's "can't scan for viruses" interstitial: resubmit its download form.
    html = resp.text
    form = re.search(r'<form[^>]*id="download-form"[^>]*action="([^"]+)"(.*?)</form>', html, re.S)
    if form:
        params = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(2)))
        resp = sess.get(form.group(1).replace("&amp;", "&"), params=params, timeout=60, headers=headers)
        resp.raise_for_status()
        if resp.content[:5] == b"%PDF-":
            return resp.content
    raise ValueError(f"not a PDF: {url} ({resp.headers.get('content-type')})")


def fetch(session=None) -> List[Record]:
    """Find the current ROAM list on the ROAM site, download it, and parse it."""
    import requests

    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}

    ids: List[str] = []
    for page_url in SITE_PAGES:
        try:
            page = sess.get(page_url, timeout=30, headers=headers)
            page.raise_for_status()
            ids += [i for i in _discover_drive_ids(page.text) if i not in ids]
        except Exception:  # noqa: BLE001 - fall back to the known id
            pass
        if ids:
            break
    if ROAM_DRIVE_ID_FALLBACK not in ids:
        ids.append(ROAM_DRIVE_ID_FALLBACK)

    candidates = [DRIVE_DOWNLOAD.format(id=i) for i in ids] + list(MIRROR_FALLBACKS)
    errors = []
    for url in candidates:
        try:
            records = parse_text(extract_pdf_text(_download_pdf(sess, url, headers)))
        except Exception as e:  # noqa: BLE001 - try the next candidate
            errors.append(f"{url}: {e}")
            continue
        if len(records) < MIN_RECORDS:
            errors.append(f"{url}: only {len(records)} records (not the member list?)")
            continue
        if url in MIRROR_FALLBACKS:
            print(f"  ! roam: Google Drive unreachable; using STALE mirror {url}", file=sys.stderr)
        return records
    raise RuntimeError("ROAM list not retrievable: " + "; ".join(errors))
