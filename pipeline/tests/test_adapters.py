"""Golden-sample tests for the ASTC and ACM adapters.

These run the pure parse functions against saved fixtures — no network, no PDF.
Run:  pip install -r pipeline/requirements.txt && pytest pipeline/tests
"""
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import astc  # noqa: E402
import acm   # noqa: E402
import narm  # noqa: E402
import roam  # noqa: E402
import aza   # noqa: E402
import ahs   # noqa: E402
import timetravelers as tt  # noqa: E402


def test_astc_parses_entries_grouped_by_state():
    text = (FIXTURES / "astc_sample.txt").read_text(encoding="utf-8")
    records = astc.parse_text(text)

    # 6 US institutions across 3 states; the EXCLUSION preamble and the CANADA
    # section are skipped (not recognized US states).
    assert len(records) == 6
    assert all(r.program == "ASTC" for r in records)
    assert all(r.source == "astc" for r in records)
    # benefit left as None so the program default (free) applies downstream.
    assert all(r.benefit is None for r in records)

    by_name = {r.name: r for r in records}
    wsc = by_name["Western Science Center"]
    assert wsc.city == "Hemet"
    assert wsc.state == "CA"
    assert wsc.id == "western-science-center-hemet-ca"

    # Punctuation in the name is preserved; trailing phone + "ID Required" stripped.
    rocket = by_name["U.S. Space & Rocket Center"]
    assert rocket.city == "Huntsville" and rocket.state == "AL"

    # A row whose phone lost its opening paren still yields a clean city.
    humboldt = by_name["Natural History Museum of Cal Poly Humboldt"]
    assert humboldt.city == "Arcata" and humboldt.state == "CA"


def test_astc_city_is_last_comma_field_when_name_has_commas():
    # Museum names can themselves contain commas; the city is the last field.
    text = "KANSAS\nExploration Place, The Sedgwick County Science Center, Wichita (316) 660-0600\n"
    records = astc.parse_text(text)
    assert len(records) == 1
    assert records[0].name == "Exploration Place, The Sedgwick County Science Center"
    assert records[0].city == "Wichita" and records[0].state == "KS"


def test_astc_entry_without_trailing_state_uses_section_header():
    text = "OHIO\nBoonshoft Museum of Discovery, Dayton\n"
    records = astc.parse_text(text)
    assert len(records) == 1
    assert records[0].state == "OH"
    assert records[0].city == "Dayton"


def test_acm_keeps_only_reciprocal_us_museums():
    data = (FIXTURES / "acm_sample.json").read_text(encoding="utf-8")
    records = acm.parse_json(data)

    names = {r.name for r in records}
    assert "Please Touch Museum" in names
    assert "Kohl Children's Museum" in names            # HTML entity decoded
    assert "Non-Reciprocal Kids Museum" not in names    # category != Reciprocal
    assert "Canadian Children's Museum" not in names    # non-US dropped
    assert len(records) == 2


def test_acm_sets_uniform_benefit_party_size_and_coords():
    data = (FIXTURES / "acm_sample.json").read_text(encoding="utf-8")
    ptm = next(r for r in acm.parse_json(data) if r.name == "Please Touch Museum")
    assert ptm.program == "ACM"
    assert ptm.benefit == "discount_50"
    assert ptm.admits == 6
    assert ptm.city == "Philadelphia" and ptm.state == "PA"
    assert ptm.website == "https://www.pleasetouchmuseum.org"
    assert ptm.id == "please-touch-museum-philadelphia-pa"
    # ACM arrives pre-geocoded, so coordinates are carried on the record.
    assert ptm.lat == 39.97417 and ptm.lng == -75.20111


def test_records_serialize_with_id():
    data = (FIXTURES / "acm_sample.json").read_text(encoding="utf-8")
    d = acm.parse_json(data)[0].to_dict()
    assert d["id"] and d["program"] == "ACM" and "raw" in d


def test_narm_parses_member_rows():
    html = (FIXTURES / "narm_sample.html").read_text(encoding="utf-8")
    records = narm.parse_html(html)
    assert len(records) == 2
    assert all(r.program == "NARM" and r.benefit is None for r in records)
    nelson = next(r for r in records if "Nelson" in r.name)
    assert nelson.city == "Kansas City" and nelson.state == "MO"
    assert nelson.website == "https://nelson-atkins.org"


def test_roam_parses_state_grouped_text():
    text = (FIXTURES / "roam_sample.txt").read_text(encoding="utf-8")
    records = roam.parse_text(text)
    assert len(records) == 3
    assert all(r.program == "ROAM" and r.benefit is None for r in records)
    dennos = next(r for r in records if "Dennos" in r.name)
    assert dennos.city == "Traverse City" and dennos.state == "MI"


def test_aza_maps_per_institution_discount():
    text = (FIXTURES / "aza_sample.txt").read_text(encoding="utf-8")
    by_name = {r.name: r for r in aza.parse_text(text)}
    assert by_name["Cincinnati Zoo & Botanical Garden"].benefit == "discount_50"
    assert by_name["San Diego Zoo"].benefit == "free"          # "Free" -> free
    assert by_name["Sacramento Zoo"].benefit == "discount_other"  # 25% -> other
    assert by_name["Cincinnati Zoo & Botanical Garden"].state == "OH"


def test_ahs_parses_geojson_feed():
    data = (FIXTURES / "ahs_sample.json").read_text(encoding="utf-8")
    records = ahs.parse_json(data)
    assert len(records) == 2
    assert all(r.program == "AHS" and r.benefit is None for r in records)
    mbg = next(r for r in records if "Missouri" in r.name)
    assert mbg.city == "St. Louis" and mbg.state == "MO"
    assert mbg.website == "https://www.missouribotanicalgarden.org"


def test_timetravelers_leaves_benefit_as_default_varies():
    html = (FIXTURES / "timetravelers_sample.html").read_text(encoding="utf-8")
    records = tt.parse_html(html)
    assert len(records) == 2
    assert all(r.program == "TIMETRAVELERS" and r.benefit is None for r in records)
    assert any(r.state == "MO" for r in records)
