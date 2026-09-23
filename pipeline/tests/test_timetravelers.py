"""Tests for the Time Travelers adapter, against rows from the real member list.

The fixture is the tab-separated extract build.py writes next to a saved page
(timetravelers.extract_html_text). City resolution uses the committed Census
tables (pipeline/place_centroids.json, data/zip_centroids.json) — no network.
"""
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import pytest  # noqa: E402

import timetravelers as tt  # noqa: E402


@pytest.fixture(scope="module")
def by_name():
    records = tt.parse_text((FIXTURES / "timetravelers_sample.txt").read_text(encoding="utf-8"))
    return {r.name: r for r in records}


def loc(r):
    return (r.city, r.state, r.zip)


def test_us_only_and_program_defaults(by_name):
    assert "TIFF" not in by_name                              # Toronto
    assert len(by_name) == 19
    assert all(r.program == "TIMETRAVELERS" and r.benefit is None for r in by_name.values())


def test_address_variants(by_name):
    assert loc(by_name["Berman Museum of World History"]) == ("Anniston", "AL", "36206")
    # spelled-out state, trailing notes, ", USA", no comma before the state, comma before ZIP
    assert loc(by_name["San Joaquin County Historical Society & Museum"]) == ("Lodi", "CA", "95240")
    assert loc(by_name["Museum of Western Colorado"]) == ("Grand Junction", "CO", "81501")
    assert loc(by_name["American Numismatic Association Money Museum"]) == ("Colorado Springs", "CO", "80903")
    assert loc(by_name["UWF Historic Trust, Pensacola"]) == ("Pensacola", "FL", "32502")
    assert loc(by_name["The National Public Housing Museum"]) == ("Chicago", "IL", "60654")
    # street runs straight into the city: the known place wins
    assert loc(by_name["History Colorado"]) == ("Denver", "CO", "80203")
    assert loc(by_name["Detroit Historical Society"]) == ("Detroit", "MI", "48202")
    # a 4-digit ZIP is dropped rather than trusted
    assert loc(by_name["Doylestown Historical Society"]) == ("Doylestown", "PA", None)


def test_glued_words_typos_and_missing_cities(by_name):
    assert by_name["Heritage Square Foundation"].city == "Phoenix"            # "St.Pheonix"
    assert by_name["Vermont Granite Museum"].city == "Barre"                  # "WayBarre"
    assert by_name["Watkins Museum of History"].city == "Lawrence"            # "Lawerence"
    assert by_name["Heritage Museum and Cultural Center"].city == "St. Joseph"  # "St. Joesph"
    assert by_name["Neligh Mill State Historic Site- History Nebraska"].city == "Neligh"  # "Wylie Dr, NE"
    assert loc(by_name["Lincoln Presidential Foundation"]) == ("Springfield", "IL", "62704")
    assert loc(by_name["Johnson County Historical Society"]) == ("Coralville", "IA", "52241")
    assert by_name["Tampa Bay History Center"].city == "Tampa"
    # A real place missing from the Census table is kept, not "corrected" to a neighbour.
    assert by_name["Dominguez Rancho Adobe Museum"].city == "Rancho Dominguez"


def test_website_gets_a_scheme(by_name):
    assert by_name["Lincoln Presidential Foundation"].website == "https://www.lincolnpresidential.org"


def test_extract_html_text_keeps_only_institution_tiles():
    html = """<div><a class="v-list__tile v-list__tile--link"><div class="v-list__tile__title">Alabama</div></a>
      <a class="v-list__tile v-list__tile--link"><div class="v-list__tile__title">Berman Museum of World History</div>
        <div class="v-list__tile__sub-title">840 Museum Drive Anniston, AL 36206</div>
        <div class="v-list__tile__sub-title">https://exploreamag.org/berman-home-page/</div></a></div>"""
    assert tt.extract_html_text(html).splitlines() == [
        "Institution\tAddress\tWebsite",
        "Berman Museum of World History\t840 Museum Drive Anniston, AL 36206\thttps://exploreamag.org/berman-home-page/",
    ]


def test_fetch_refuses_because_the_site_opts_out():
    with pytest.raises(RuntimeError, match="manual_drops/timetravelers"):
        tt.fetch()
