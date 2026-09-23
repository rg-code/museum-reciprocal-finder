"""Golden-sample tests for the NARM adapter.

These run the pure functions against real snippets of the Fall 2026 member-list
PDF -- no network, no PDF parsing:
  * narm_sample.txt        -- reconstructed rows (parse_text input)
  * narm_words_sample.json -- raw pdfplumber words (lines_from_words input)
Run:  pytest pipeline/tests/test_narm.py
"""
import json
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import narm  # noqa: E402


def _records():
    return narm.parse_text((FIXTURES / "narm_sample.txt").read_text(encoding="utf-8"))


def test_parse_text_keeps_us_rows_only():
    records = _records()
    # 15 US/PR rows; the intro prose and the Canada row are dropped.
    assert len(records) == 15
    assert all(r.program == "NARM" and r.source == "narm" for r in records)
    assert all(r.country == "US" for r in records)
    assert all(r.benefit is None and r.admits is None for r in records)  # program default
    assert all(len(r.state) == 2 and r.state.isupper() for r in records)
    assert not any("Kenora" in (r.city or "") or r.name.startswith("The Muse |") for r in records)
    assert {r.state for r in records} == {"PR", "AL", "CA", "CO", "DC", "FL", "IN", "LA", "ME", "MA", "MS", "PA"}


def test_parse_text_basic_row_and_puerto_rico():
    by_name = {r.name: r for r in _records()}
    abroms = by_name["Abroms-Engel Institute for Visual Arts"]
    assert (abroms.city, abroms.state) == ("Birmingham", "AL")
    assert abroms.id == "abroms-engel-institute-for-visual-arts-birmingham-al"
    assert abroms.raw.startswith("Birmingham, Abroms-Engel")
    # Puerto Rico is its own (non-state) section in the PDF but counts as US.
    musan = by_name["MUSAN | Museo de los Santos y Arte Nacional"]
    assert (musan.city, musan.state) == ("San Juan", "PR")


def test_parse_text_rejoins_wrapped_rows():
    by_name = {r.name: r for r in _records()}
    # "...San Diego (Central" + "Campus), 760-436-6611"
    ica = by_name["The Institute of Contemporary Art, San Diego (Central Campus)"]
    assert (ica.city, ica.state) == ("San Diego", "CA")
    # Tail line itself contains ", " but starts with a lowercase connector.
    noaam = by_name["The New Orleans African American Museum of Art, Culture, and History"]
    assert (noaam.city, noaam.state) == ("New Orleans", "LA")


def test_parse_text_rows_without_phone_are_not_merged():
    by_name = {r.name: r for r in _records()}
    # No phone at all -> kept standalone, next row not swallowed.
    assert by_name["east window"].city == "Boulder"
    assert by_name["Whittier Home & Museum"].city == "Amesbury"
    assert by_name["Addison Gallery of American Art"].city == "Andover"


def test_parse_text_cleans_names_cities_and_phones():
    by_name = {r.name: r for r in _records()}
    # Restriction markers stripped; phone glued to the comma.
    assert by_name["Fine Arts Museum - de Young Museum"].city == "San Francisco"
    # Phone with an extension suffix ("970-243-7337x2") doesn't leak into the name.
    assert "Western Colorado Center for the Arts (The Art Center)" in by_name
    # 7-digit phone with no area code.
    assert by_name["Maritime and Seafood Industry Museum"].city == "Biloxi"
    # Pipe spacing normalized.
    assert "Lincoln County Historical Association | Pownalborough Court House" in by_name
    # Parenthetical note removed from the city.
    assert by_name["Tyler Arboretum"].city == "Media"
    for r in by_name.values():
        assert not any(ch.isdigit() for ch in r.city)
        assert "*" not in r.name and "#" not in r.name and "  " not in r.name
        assert not r.name.endswith(",")


def test_parse_text_dc_header_supplies_city():
    by_name = {r.name: r for r in _records()}
    # "# District of Columbia, Washington" rows are just "Name, phone"; the
    # comma inside the name must not be read as a city.
    hillwood = by_name["Hillwood Estate, Museum and Gardens"]
    assert (hillwood.city, hillwood.state) == ("Washington", "DC")


def test_parse_text_distance_markers_set_exclusion():
    by_name = {r.name: r for r in _records()}
    # "**" = not extended to other institutions' members within 15 miles.
    assert by_name["Newfields"].exclusion == {"radius_mi": 15, "anchors": ["home_institution"]}
    # "#" = 50 miles.
    assert by_name["The Dalí Museum"].exclusion == {"radius_mi": 50, "anchors": ["home_institution"]}
    # "*" (special events only) and unmarked rows -> None (program default).
    assert by_name["Fine Arts Museum - de Young Museum"].exclusion is None
    assert by_name["Abroms-Engel Institute for Visual Arts"].exclusion is None
    assert by_name["The Dalí Museum"].raw.endswith("Museum#, 727-823-3767")   # marker kept in raw


def test_parse_text_website_when_printed():
    by_name = {r.name: r for r in _records()}
    assert by_name["Newfields"].website == "https://discovernewfields.org"
    assert by_name["Newfields"].city == "Indianapolis"
    assert by_name["Abroms-Engel Institute for Visual Arts"].website is None


def test_lines_from_words_splits_columns_and_drops_footer():
    data = json.loads((FIXTURES / "narm_words_sample.json").read_text(encoding="utf-8"))
    page1, page4 = data["pages"]
    lines = narm.lines_from_words(page1["words"], page1["width"], page1["height"])

    assert "# United States" in lines and "# Alabama" in lines
    assert "Birmingham, Abroms-Engel Institute for Visual Arts, 205-975-6436" in lines
    # Column 1 prose runs ~10pt past its column; its overflow words ("with",
    # "and") must not be glued onto column-2 rows.
    assert "Montgomery, Montgomery Museum of Fine Arts, 334-240-4333" in lines
    assert not any(l.startswith(("with ", "and ", "nd ")) for l in lines)
    # The restriction legend / copyright at the page bottom is cut.
    assert not any("NARM privileges" in l or "rights reserved" in l for l in lines)
    # Columns come out in reading order: column 2 before column 3.
    assert lines.index("# Alabama") < lines.index("Berkeley, UC Berkeley Art Museum##, 510-642-0808")

    # A row whose tail is set in a smaller (lower-baseline) font stays one line.
    lines4 = narm.lines_from_words(page4["words"], page4["width"], page4["height"])
    assert ("Dresden, Lincoln County Historical Association| Pownalborough Court House, "
            "207-882-6817") in lines4

    # End to end: only rows under US state headers become records; prose is ignored.
    # The state header carries over into the next column (California -> Berkeley rows).
    records = narm.parse_text("\n".join(lines))
    assert len(records) == 12 + 19   # Alabama + California rows in the snippet (no Canada rows)
    assert {r.state for r in records} == {"AL", "CA"}
    assert not any(r.city in ("ON", "Toronto") for r in records)
    by_name = {r.name: r for r in records}
    assert by_name["Montgomery Museum of Fine Arts"].state == "AL"
    assert (by_name["UC Berkeley Art Museum"].city, by_name["UC Berkeley Art Museum"].state) == ("Berkeley", "CA")
    assert "USS Hornet Museum" in by_name   # "510-521-8448 ex 286" tail dropped


def test_discover_pdf_url_prefers_member_list_link():
    html = (
        '<a href="https://narmassociation.org/wp-content/uploads/2020/01/brochure.pdf">Brochure</a>'
        '<li id="menu-item-5801"><a target="_blank" '
        'href="https://narmassociation.org/wp-content/uploads/2026/09/NARM_FALL_2026_FINAL.pdf">'
        "Download NARM Member List</a></li>"
    )
    assert narm.discover_pdf_url(html) == (
        "https://narmassociation.org/wp-content/uploads/2026/09/NARM_FALL_2026_FINAL.pdf"
    )
    assert narm.discover_pdf_url("<p>no links</p>") is None
