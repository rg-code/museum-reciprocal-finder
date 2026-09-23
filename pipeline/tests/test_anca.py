"""Tests for the ANCA adapter, against rows from the real reciprocal-program table."""
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import pytest  # noqa: E402

import anca  # noqa: E402


@pytest.fixture(scope="module")
def by_name():
    records = anca.parse_html((FIXTURES / "anca_sample.html").read_text(encoding="utf-8"))
    return {r.name: r for r in records}


def test_rows_names_cities_states_and_sites(by_name):
    assert len(by_name) == 15
    k = by_name["Kreher Preserve & Nature Center"]
    assert (k.city, k.state, k.program, k.source) == ("Auburn", "AL", "ANCA", "anca")
    assert k.website == "https://www.auburn.edu/preserve"
    assert by_name["Center For Alaskan Coastal Studies"].state == "AK"
    assert by_name["Tracy Aviary"].city == "Salt Lake City"          # printed "Salt Lake"


def test_benefit_mapping(by_name):
    b = {n: r.benefit for n, r in by_name.items()}
    assert b["Kreher Preserve & Nature Center"] == "free"             # "Free Admission; Discounted Programs"
    assert b["Fontenelle Forest"] == "discount_50"                    # "50% Admission Discount"
    assert b["Center For Alaskan Coastal Studies"] == "discount_other"  # 20%
    assert b["Okefenokee Swamp Park"] == "discount_other"             # 25%
    assert b["Reflection Riding Arboretum and Nature Center"] == "discount_other"  # free with one paid adult
    assert b["Roper Mountain Science Center"] == "varies"            # summer-only free admission
    assert b["Earthplace"] == "varies"                               # store discount only
    assert b["McDowell Environmental Center"] == "varies"            # "please contact"


def test_party_size_and_50_mile_rule(by_name):
    assert by_name["DNR Outdoor Adventure Center"].admits == 5          # "Up to 5 people"
    assert by_name["Swaner Preserve and EcoCenter, Utah State University"].admits == 6
    rule = {"radius_mi": 50, "anchors": ["home_institution"]}
    assert by_name["Cincinnati Nature Center"].exclusion == rule      # "excludes organizations within 50 miles"
    assert by_name["Gorman Heritage Farm Foundation"].exclusion == rule
    assert by_name["Kreher Preserve & Nature Center"].exclusion is None


def test_fetch_guards_against_a_broken_page(monkeypatch):
    class Resp:
        text = "<html><table></table></html>"
        def raise_for_status(self): pass
    class Sess:
        def get(self, *a, **k): return Resp()
    with pytest.raises(ValueError, match="only 0 organizations"):
        anca.fetch(session=Sess())
