"""AZA (Association of Zoos & Aquariums) Reciprocal Admissions adapter.

Source: AZA's annual reciprocity PDF (May-April cycle) from aza.org/reciprocity.
aza.org opts out of automated access (robots.txt disallows automated agents and
/reciprocity sits behind a Cloudflare bot challenge), so the PDF is downloaded
by hand into pipeline/manual_drops/aza/. build.py turns it into a same-named
.txt with `extract_pdf_text()` — only that .txt is committed — and parses it
with `parse_text()`.

Layout (verified on the 2026-27 list, "Updated 8/20/26"): 5 landscape pages, a
table State | City | Zoo or Aquarium | Reciprocity | Contact Name | Phone #,
with a prose sidebar on the right. Reciprocity text is printed in color (red
50%, blue 100% OR 50%, green FREE TO PUBLIC) and everything else in black, which
is how its wrapped notes are told apart from names. The State cell is blank
under the first row of each state.

Benefit is in-kind, per the sidebar legend:
- "50%"            -> discount_50 for every member.
- "100% OR 50%"    -> 100% for members of other "100% OR 50%" zoos, else 50%.
                      Emitted as discount_50 with tier "100_or_50"; the app
                      upgrades it to free when the user's home zoo shares it.
- "FREE TO PUBLIC" -> free for everyone (tier "free_public").
- "(Limit N)"      -> admits N. Anything else -> "varies" (call ahead).
"""
from __future__ import annotations

import re
from typing import List, Optional

from _common import Record, state_header

SOURCE = "aza"
PROGRAM = "AZA"
# Checked 2026-09-23: aza.org/robots.txt disallows automated agents and
# /reciprocity sits behind a Cloudflare bot challenge (HTTP 403). We don't
# scrape sources that opt out, so this program is fed only by a manual drop.
BLOCKED_REASON = ("aza.org/robots.txt disallows automated agents and /reciprocity sits "
                  "behind a Cloudflare bot challenge (HTTP 403)")

HEADER = "State\tCity\tInstitution\tReciprocity"
# Column starts (pt) on the 792pt-wide page; the sidebar begins at ~613.
CITY_X, NAME_X, CONTACT_X, SIDEBAR_X = 74.0, 150.0, 406.0, 610.0
_LIMIT = re.compile(r"\(\s*limit\s+(\d+)\s*\)", re.I)
_FOOTER = re.compile(r"^(\*|please note)", re.I)


def _is_black(w: dict) -> bool:
    c = w.get("non_stroking_color")
    return not c or all(v == 0 for v in (c if isinstance(c, (list, tuple)) else [c]))


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """PDF -> tab-separated State, City, Institution, Reciprocity (one row per line)."""
    import io
    import pdfplumber  # imported lazily so unit tests don't need it

    rows: List[List[str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = [w for w in page.extract_words(x_tolerance=1.5, extra_attrs=["non_stroking_color"])
                     if w["x0"] < SIDEBAR_X]
            header = next((w for w in words if w["text"] == "Reciprocity"), None)
            if not header:
                continue
            words = sorted((w for w in words if w["top"] > header["bottom"] + 1),
                           key=lambda w: (w["top"], w["x0"]))
            lines: List[List[dict]] = []
            for w in words:
                if lines and abs(lines[-1][0]["top"] - w["top"]) < 2.5:
                    lines[-1].append(w)
                else:
                    lines.append([w])
            for line in lines:
                line.sort(key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in line)
                if _FOOTER.match(text):
                    break                    # legend/notes at the foot of the page
                black = [w for w in line if _is_black(w)]
                pick = lambda lo, hi: " ".join(w["text"] for w in black if lo <= w["x0"] < hi)
                state, city, name = pick(0, CITY_X), pick(CITY_X, NAME_X), pick(NAME_X, CONTACT_X)
                recip = " ".join(w["text"] for w in line if not _is_black(w) and w["x0"] < CONTACT_X)
                if name or city or state:
                    rows.append([state, city, name, recip])
                elif recip and rows:         # wrapped reciprocity note
                    rows[-1][3] = f"{rows[-1][3]} {recip}".strip()
    return "\n".join([HEADER] + ["\t".join(r) for r in rows]) + "\n"


def _benefit(recip: str):
    """Reciprocity text -> (benefit, tier, admits)."""
    t = recip.upper()
    m = _LIMIT.search(recip)
    admits = int(m.group(1)) if m else None
    if t.startswith("FREE TO PUBLIC"):   # a "(Limit N)" here caps an add-on, not entry
        return "free", "free_public", None
    if t.startswith("100% OR 50%"):
        return "discount_50", "100_or_50", admits
    if t.startswith("50%"):
        return "discount_50", None, admits
    return "varies", None, admits


def parse_text(text: str) -> List[Record]:
    """Parse the tab-separated extract into US AZA Records (non-US rows dropped)."""
    records: List[Record] = []
    state: Optional[str] = None
    in_us = False
    for line in text.splitlines():
        if not line.strip() or line.startswith("State\t"):
            continue
        cells = (line.split("\t") + ["", "", "", ""])[:4]
        st_cell, city, name, recip = (c.strip() for c in cells)
        if st_cell:                          # a new state/country section
            state = state_header(st_cell)
            in_us = state is not None
        if not in_us or not name:
            continue
        benefit, tier, admits = _benefit(recip)
        records.append(Record(
            program=PROGRAM, name=name, city=city or None, state=state,
            benefit=benefit, admits=admits, tier=tier,
            source=SOURCE, raw=f"{st_cell or state} | {city} | {name} | {recip}",
        ))
    return records


def fetch(session=None, url: str = "") -> List[Record]:
    """Not fetched automatically — the source opts out of automated access."""
    raise RuntimeError(
        f"AZA is not scraped ({BLOCKED_REASON}). Put the current reciprocity PDF "
        "(May-April cycle) from https://www.aza.org/reciprocity in "
        "pipeline/manual_drops/aza/ instead."
    )
