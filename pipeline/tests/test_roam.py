"""Golden-sample tests for the ROAM adapter.

The fixture is real rows trimmed from the ROAM "Website Listing" PDF (March
2026), as produced by `roam.extract_pdf_text()` — no network, no PDF needed.
Run:  pytest pipeline/tests/test_roam.py
"""
import sys
from pathlib import Path

import pytest

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import roam  # noqa: E402


@pytest.fixture(scope="module")
def records():
    return roam.parse_text((FIXTURES / "roam_sample.txt").read_text(encoding="utf-8"))


def by_name(records):
    return {r.name: r for r in records}


def test_parses_us_rows_only(records):
    # 12 US museums; title/legend/header rows and the Online, Ontario and
    # Panamá rows are skipped.
    assert len(records) == 12
    assert all(r.program == "ROAM" and r.source == "roam" for r in records)
    assert all(r.benefit is None and r.admits is None for r in records)  # program default
    assert all(r.country == "US" for r in records)
    assert all(r.state and len(r.state) == 2 for r in records)
    names = by_name(records)
    assert "The Hunger Museum" not in names
    assert "Art Gallery of Ontario" not in names
    assert "MAC Panamá" not in names
    assert not any("ROAM" in n or n in ("Museum", "State Full") for n in names)


def test_basic_row(records):
    r = by_name(records)["Anchorage Museum"]
    assert (r.city, r.state) == ("Anchorage", "AK")
    assert r.id == "anchorage-museum-anchorage-ak"
    # restriction symbols + details are kept for auditing, not in the name
    assert "Premier exhibitions" in r.raw and "‡" in r.raw
    assert r.exclusion is None  # no "+" marker


def test_plus_marker_sets_25_mile_exclusion(records):
    names = by_name(records)
    assert names["Edsel & Eleanor Ford House"].exclusion == {
        "radius_mi": 25, "anchors": ["inter_institution"]}
    assert sum(r.exclusion is not None for r in records) == 2  # Ford House, Shaker Museum


def test_clipped_and_misspelled_state_names(records):
    names = by_name(records)
    assert names["Hillwood Estate, Museum & Gardens"].state == "DC"      # "District of Co"
    assert names["Boston Athenaeum"].state == "MA"                       # "Massachusett"
    assert names["Boston Athenaeum"].city == "Boston"                    # not "ttBoston"
    assert names["Historic Beverly"].state == "MA"                       # "Massachusse" typo
    assert names["deCordova Sculpture Park and Museum"].city == "Lincoln"


def test_wrapped_cells_and_punctuation(records):
    names = by_name(records)
    assert (
        "Carolyn Campagna Kleefeld Contemporary Art Museum California State University Long Beach"
        in names
    )
    assert names["Edsel & Eleanor Ford House"].city == "Grosse Pointe Shores"
    assert names["Shaker Museum | Mount Lebanon"].state == "NY"
    assert "Hillwood Estate, Museum & Gardens" in names  # comma inside the name


def test_source_errors_are_corrected(records):
    names = by_name(records)
    assert names["Laurel Hill Cemetery"].city == "Philadelphia"
    assert names["Thelma Sadoff Center for the Arts"].city == "Fond du Lac"
    swift = names["Swift County Historical Society"]
    assert (swift.city, swift.state) == ("Benson", "MN")  # listed under Michigan


@pytest.mark.parametrize("value,code", [
    ("California", "CA"), ("North Carolin", "NC"), ("South Carolin", "SC"),
    ("District of Co", "DC"), ("New Hampsh", "NH"), ("Massachusse", "MA"),
    ("West Virginia", "WV"), ("Virginia", "VA"), ("Washington", "WA"),
    ("Hawai‘i", "HI"), ("PR", "PR"), ("tx", "TX"),
    ("Ontario", None), ("Québec", None), ("British Colum", None), ("New Brunsw", None),
    ("Nova Scotia", None), ("Prince Edwar", None), ("Saskatchewa", None),
    ("Mexico", None), ("Cayman Islan", None), ("Online", None), ("New", None), ("", None),
])
def test_resolve_state(value, code):
    assert roam.resolve_state(value) == code


def test_older_layout_with_codes_and_country_rows():
    # Aug-2025 files used 2-letter codes and "United States"/"Canada" rows.
    text = "\n".join([
        "State\tCity\tMuseum\tRestrictions\tRestriction Details",
        "United States\t\t\t\t",
        "Online Museum\t\tThe Hunger Museum\t*\t",
        "AL\tAuburn\tJule Collins Smith Museum of Fine Art\t*\t",
        "Canada\t\t\t\t",
        "ON\tToronto\tGardiner Museum\t* + ‡\tSelected special exhibitions",
    ])
    recs = roam.parse_text(text)
    assert [(r.name, r.city, r.state) for r in recs] == [
        ("Jule Collins Smith Museum of Fine Art", "Auburn", "AL")]


def test_csv_manual_drop():
    text = 'State,City,Museum,Restrictions\nTexas,Houston,"Houston Center for Contemporary Craft",*\n'
    recs = roam.parse_text(text)
    assert [(r.name, r.city, r.state) for r in recs] == [
        ("Houston Center for Contemporary Craft", "Houston", "TX")]


def test_discover_drive_ids():
    html = (
        '<a href="https://drive.google.com/file/d/1lam68fgSi2MxRhZtIywp2oq_skfu62Xa/view?usp=sharing">'
        'List of Participating ROAM Museums</a>'
        '<a href="https://drive.google.com/open?id=1ABCdefGHIjklMNOpqrSTUvwxYZ012345">x</a>'
        '<a href="https://drive.google.com/file/d/1lam68fgSi2MxRhZtIywp2oq_skfu62Xa/view">dup</a>'
    )
    assert roam._discover_drive_ids(html) == [
        "1lam68fgSi2MxRhZtIywp2oq_skfu62Xa", "1ABCdefGHIjklMNOpqrSTUvwxYZ012345"]


def test_glyph_straddling_cell_border_stays_in_its_cell():
    pytest.importorskip("pdfplumber")

    def ch(text, x0, x1, top=100.0):
        return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 9,
                "doctop": top, "upright": True, "size": 9}

    # Real geometry from the PDF: State cell 50-92, City cell 92-160; the
    # clipped "tt" ligature of "Massachusetts" spans 89.8-94.7.
    cells = [(50.0, 98.0, 92.0, 112.0), (92.0, 98.0, 160.0, 112.0), None]
    chars = [ch("Massachuse", 52.1, 89.9), ch("tt", 89.8, 94.7),
             ch("Boston", 93.7, 118.0), ch("Other row", 52.1, 90.0, top=130.0)]
    assert roam._cells_text(cells, chars) == ["Massachusett", "Boston", ""]
