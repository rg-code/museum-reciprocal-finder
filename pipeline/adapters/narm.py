"""NARM (North American Reciprocal Museum Association) adapter.

Source: the "Download NARM Member List" PDF linked from every page of
narmassociation.org (footer/menu), e.g.
https://narmassociation.org/wp-content/uploads/2026/09/NARM_FALL_2026_FINAL.pdf
It is re-issued quarterly (mid-Dec/Mar/Jun/Sep) under a new upload path, so
`fetch()` scrapes the current link from the /members/ page and falls back to
the last known URL.

Why the PDF and not the /members/ map: the map is a server-rendered search
(`/members/?keyword=&loc=&r=&cat=`) that shows nothing without a query, the
category pages 301 to `/members/?cat=N`, and robots.txt has `Disallow: /*?`
plus `Crawl-delay: 10`. The PDF is a plain static file, so the whole fetch is
two polite GETs (page + PDF, 10 s apart). The PDF has no addresses, ZIPs,
coordinates, or per-member benefit, so records carry only name/city/state
(plus a website on the rare row that prints one) and get geocoded downstream.

Layout (verified against the Fall 2026 file, 9 landscape pages): 3 columns,
left margins x~36/280/523 on a 792 pt page. Bold lines are section headers --
non-US regions first ("Bermuda", "Canada", "Cayman Islands", "Puerto Rico"),
then "United States" and one header per state ("District of Columbia,
Washington" for DC). Rows are "City, Name[marker], phone[ extra]"; long names
wrap onto a second line, a few rows have no phone, and some rows are set in a
smaller font. A restriction legend and copyright block sit at the bottom of
every page; it defines the markers printed after a name:
    *    may be restricted for concerts/lectures/special exhibitions/ticketed events
    **   not extended to other institutions' members within a 15-mile radius
    ***  both of the above
    #    not extended to other institutions' members within a 50-mile radius
    ##   does not apply to the Pacific Film Archive (UC Berkeley)
    ^    not extended to members of institutions that restrict this one
Only the distance rules are modeled: ** / *** set
`exclusion={"radius_mi": 15, "anchors": ["home_institution"]}` and # sets the
50-mile version; unmarked rows leave `exclusion` None (program default). No
marker changes the benefit type, so benefit stays None (program default: free).
Markers are kept in `raw` for auditing.

Design: `extract_pdf_text()` rebuilds the columns into one normalized line per
row (headers prefixed with "# "), via the pure `lines_from_words()`;
`parse_text()` turns those lines into Records. Tests exercise both offline.

US-only for v1: rows under non-US headers are dropped; Puerto Rico is kept.
Verified live (Sep 2026, Fall 2026 list): 1,532 US institutions (incl. 16 DC,
1 PR) plus 30 non-US rows (Canada 27, Bermuda 2, Cayman Islands 1).
"""
from __future__ import annotations

import html
import re
import time
from typing import Iterable, List, Optional, Tuple

from _common import Record, state_header

NARM_MEMBERS_URL = "https://narmassociation.org/members/"
# Fallback if the members page can't be scraped for the current link.
NARM_PDF_FALLBACK = (
    "https://narmassociation.org/wp-content/uploads/2026/09/NARM_FALL_2026_FINAL.pdf"
)
SOURCE = "narm"
PROGRAM = "NARM"
USER_AGENT = "museum-reciprocal-finder/0.2 (personal project)"
CRAWL_DELAY = 10  # seconds; robots.txt asks for Crawl-delay: 10
MIN_EXPECTED = 500  # the Fall 2026 list has ~1,530 US rows

HEADER_PREFIX = "# "

# A phone anywhere in the row: "205-975-6436", "(661) 723-6000", "831 372-5477",
# "909-980- 0412" (wrapped), "513-721-ARTS", "970-243-7337x2", truncated
# "667-222-181", or a trailing 7-digit number with no area code ("435-6320").
_PHONE = re.compile(
    r"\(?\b\d{3}\)?[\s.\-]*\d{3}[\s.\-]*[0-9A-Z]{3,4}(?!\d)"
    r"|\b\d{3}-\d{4}\s*$"
)
# A wrapped tail that happens to contain ", " ("Culture, and History, 504-...")
# is still a tail if its second part starts with a lowercase connector.
_CONNECTOR_TAIL = re.compile(r"^[^,]+,\s+(?:and|&|or|of|for|in|at|on)\b")
# A bare web address printed after the phone ("..., 317-923-1331, discovernewfields.org").
_DOMAIN = re.compile(r"\b((?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:org|com|net|edu|gov|museum|us)\b[^\s,;]*)", re.I)
# Restriction markers after a name ("Heard Museum*", "The Momentary***", "Dalí Museum#").
_MARKERS = re.compile(r"[*#^]+")
# Per-institution distance rules from the PDF legend (see module docstring).
EXCLUSION_15MI = {"radius_mi": 15, "anchors": ["home_institution"]}
EXCLUSION_50MI = {"radius_mi": 50, "anchors": ["home_institution"]}


# ---- Text -> Records (pure) -------------------------------------------------
def parse_text(text: str) -> List[Record]:
    """Parse the reconstructed member-list text into NARM Records.

    Input is one item per line: "# Header" section lines (country / state), or
    "City, Name, phone" rows. A row whose name wrapped in the PDF may arrive as
    two lines; they are rejoined here.
    """
    records: List[Record] = []
    state: Optional[str] = None      # 2-letter, or None outside a US section
    section_city: Optional[str] = None  # DC's header names the city; its rows don't
    pending: Optional[str] = None    # a row still waiting for its phone/continuation

    def flush():
        nonlocal pending
        if pending is not None and state:
            rec = _parse_row(pending, state, section_city)
            if rec:
                records.append(rec)
        pending = None

    for raw_line in text.splitlines():
        line = _norm_space(html.unescape(raw_line))
        if not line:
            continue

        header = _header_state(line)
        if header is not None:            # a section header (US state or not)
            flush()
            state, section_city = header
            continue

        if pending is not None:
            if _is_continuation(line):
                pending = f"{pending} {line}"
                if _has_phone(pending):
                    flush()
                continue
            flush()                        # previous row simply had no phone

        pending = line
        if _has_phone(line):
            flush()

    flush()
    return records


# Kept for callers that still use the old name (build.py manual drops/fixtures).
parse_html = parse_text


def _header_state(line: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """For a header line return (2-letter code or None if non-US, section city).

    Returns None if `line` is not a header. The section city is only set for a
    header like "District of Columbia, Washington", whose rows omit the city.
    """
    if line.startswith(HEADER_PREFIX.strip()):
        title = line.lstrip("#").strip()
    elif "," not in line and not re.search(r"\d", line) and state_header(line):
        title = line                       # an un-marked bare state name ("Ohio")
    else:
        return None
    if not title or title.isdigit():       # bold page numbers
        return None
    code = state_header(title)
    if code:
        return code, None
    # "District of Columbia, Washington" -> state from one part, city from the rest.
    parts = [p.strip() for p in title.split(",")]
    for i, part in enumerate(parts):
        code = state_header(part)
        if code:
            rest = ", ".join(parts[:i] + parts[i + 1:]).strip()
            return code, (rest or None)
    return None, None


def _has_phone(s: str) -> bool:
    return bool(_PHONE.search(s))


def _is_continuation(line: str) -> bool:
    """True if `line` is the wrapped tail of the previous row, not a new row.

    Every real row starts "City, Name..."; a wrapped tail is just the end of a
    name plus the phone ("Project, 408-918-1053", "(SAAACAM), 210-724-3350",
    "807-467-2202") -- i.e. no ", " left once the phone is removed.
    """
    head = _PHONE.split(line, maxsplit=1)[0].strip().rstrip(",").strip()
    return ", " not in head or bool(_CONNECTOR_TAIL.match(head))


def _parse_row(row: str, state: str, section_city: Optional[str] = None) -> Optional[Record]:
    m = _PHONE.search(row)
    head, tail = (row[: m.start()], row[m.end():]) if m else (row, "")
    head = head.strip().rstrip(",").strip()
    if section_city:                     # DC rows: "Name, phone" (name may hold commas)
        city, name = section_city, head
    else:
        city, sep, name = head.partition(",")
        if not sep:
            return None
    city = re.sub(r"\s*\(.*?\)", "", _MARKERS.sub("", city))   # "Media (greater ... region)"
    city = _norm_space(city).strip(" ,")
    city = re.sub(r"(?<=[a-z]{2}) (?=[a-z]$)", "", city)       # PDF glyph gap: "Derb y" -> "Derby"
    name = _clean_name(name)
    if not city or not name or any(ch.isdigit() for ch in city):
        return None

    website = None
    wm = _DOMAIN.search(tail)
    if wm:
        website = wm.group(1).rstrip(".")
        if not website.lower().startswith("http"):
            website = "https://" + website

    return Record(
        program=PROGRAM,
        name=name,
        city=city,
        state=state,
        benefit=None,          # program default: free
        exclusion=_exclusion(row),
        website=website,
        source=SOURCE,
        raw=row[:200],
    )


def _exclusion(row: str) -> Optional[dict]:
    """Distance rule from the row's restriction markers, or None (program default)."""
    radius = 0
    for run in _MARKERS.findall(row):
        if run.count("#") == 1:
            radius = max(radius, 50)
        if run.count("*") >= 2:
            radius = max(radius, 15)
    if radius == 50:
        return dict(EXCLUSION_50MI, anchors=list(EXCLUSION_50MI["anchors"]))
    if radius == 15:
        return dict(EXCLUSION_15MI, anchors=list(EXCLUSION_15MI["anchors"]))
    return None


def _clean_name(name: str) -> str:
    name = _MARKERS.sub("", name)
    name = re.sub(r"\s*\|\s*", " | ", name)          # "Society|Museum" -> "Society | Museum"
    name = re.sub(r"\s+,", ",", name)                 # "(Chhange) ," -> "(Chhange),"
    name = re.sub(r"(?<=\w)- (?=[A-Z])", "-", name)   # "Ohr- O'Keefe" -> "Ohr-O'Keefe"
    name = _norm_space(name).strip(" ,;")
    return name


def _norm_space(s: str) -> str:
    """Collapse whitespace (incl. NBSP) and straighten curly apostrophes."""
    s = re.sub(r"[\u2018\u2019]", "'", s)
    return re.sub(r"[\s\u00a0]+", " ", s).strip()


# ---- PDF words -> lines (pure; the fragile layout logic lives here) ---------
def lines_from_words(words: Iterable[dict], page_width: float, page_height: float) -> List[str]:
    """Rebuild one page's rows from pdfplumber-style word dicts.

    Each word needs x0, x1, top, text and fontname. Columns are split at the
    gutters -- vertical strips no word touches (the intro prose on page 1 runs
    ~10 pt past its column, so fixed x cut-offs are not safe). Words are then
    grouped into lines by `top` (smaller-font words sit ~0.7 pt lower, so a
    2.5 pt tolerance is used). The legend/copyright block at the bottom of every
    page is cut off at its "Restrictions" heading (fallback: bottom 16%). Lines
    whose words are all bold are emitted as "# Header".
    """
    words = [w for w in words if str(w.get("text", "")).strip()]
    if not words:
        return []

    footer_top = page_height * 0.84
    for w in words:
        if w["text"].strip().lower().startswith("restrictions") and w["top"] > page_height * 0.5:
            footer_top = min(footer_top, w["top"] - 2)
    words = [w for w in words if w["top"] < footer_top]

    splits = _gutters(words, page_width)
    columns: List[List[dict]] = [[] for _ in range(len(splits) + 1)]
    for w in words:
        columns[sum(1 for x in splits if w["x0"] >= x)].append(w)

    out: List[str] = []
    for col in columns:
        col.sort(key=lambda w: (w["top"], w["x0"]))
        lines: List[List[dict]] = []
        for w in col:
            if lines and abs(w["top"] - lines[-1][0]["top"]) <= 2.5:
                lines[-1].append(w)
            else:
                lines.append([w])
        for ln in lines:
            ln.sort(key=lambda w: w["x0"])
            text = _norm_space(" ".join(w["text"] for w in ln))
            if not text:
                continue
            if all("bold" in str(w.get("fontname", "")).lower() for w in ln):
                text = HEADER_PREFIX + text
            out.append(text)
    return out


def _gutters(words: List[dict], page_width: float, min_gap: int = 6) -> List[float]:
    """x positions (midpoints) of the empty vertical strips between columns."""
    import math

    covered = [False] * (int(page_width) + 2)
    for w in words:
        for x in range(max(0, int(w["x0"])), min(len(covered), int(math.ceil(w["x1"])))):
            covered[x] = True
    lo, hi = page_width * 0.1, page_width * 0.9
    splits: List[float] = []
    start = None
    for x, cov in enumerate(covered + [True]):
        if not cov and start is None:
            start = x
        elif cov and start is not None:
            if x - start >= min_gap and lo < start and x < hi:
                splits.append((start + x) / 2)
            start = None
    return splits


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Turn the member-list PDF into parse_text() input (one row per line)."""
    import io
    import pdfplumber  # imported lazily so parse tests don't need it

    lines: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, extra_attrs=["fontname", "size"])
            lines.extend(lines_from_words(words, float(page.width), float(page.height)))
    return "\n".join(lines)


# ---- Live fetch --------------------------------------------------------------
def discover_pdf_url(page_html: str) -> Optional[str]:
    """Find the current "Download NARM Member List" PDF link in a site page."""
    from urllib.parse import urljoin

    anchors = re.findall(r'<a\b[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', page_html, flags=re.I | re.S)
    for href, label in anchors:
        if "member list" in re.sub(r"<[^>]+>", " ", label).lower():
            return urljoin(NARM_MEMBERS_URL, html.unescape(href))
    for href, _ in anchors:
        if re.search(r"/wp-content/uploads/.*NARM.*\.pdf$", href, flags=re.I):
            return urljoin(NARM_MEMBERS_URL, html.unescape(href))
    return None


def fetch(session=None) -> List[Record]:
    """Find the current member-list PDF, download it, and parse it.

    Two requests total (members page, then the PDF), spaced by robots.txt's
    Crawl-delay. Raises if the result is implausibly small, so a silent layout
    change fails the source loudly instead of publishing a near-empty NARM list.
    """
    import requests

    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    url = NARM_PDF_FALLBACK
    try:
        page = sess.get(NARM_MEMBERS_URL, timeout=30, headers=headers)
        page.raise_for_status()
        url = discover_pdf_url(page.text) or url
    except Exception:  # noqa: BLE001 - fall back to the last known URL
        pass
    time.sleep(CRAWL_DELAY)   # honor robots.txt Crawl-delay between requests

    resp = sess.get(url, timeout=90, headers=headers)
    resp.raise_for_status()
    records = parse_text(extract_pdf_text(resp.content))
    if len(records) < MIN_EXPECTED:
        raise ValueError(f"narm: only {len(records)} US records parsed from {url}; layout changed?")
    return records
