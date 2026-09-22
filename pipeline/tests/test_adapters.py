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


def test_astc_parses_entries_grouped_by_state():
    text = (FIXTURES / "astc_sample.txt").read_text(encoding="utf-8")
    records = astc.parse_text(text)

    # 6 institutions across 3 states; header/footer lines skipped.
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

    # Name containing punctuation is preserved (rsplit keeps commas in the name).
    rocket = by_name["U.S. Space & Rocket Center"]
    assert rocket.city == "Huntsville" and rocket.state == "AL"


def test_astc_entry_without_trailing_state_uses_section_header():
    text = "OHIO\nBoonshoft Museum of Discovery, Dayton\n"
    records = astc.parse_text(text)
    assert len(records) == 1
    assert records[0].state == "OH"
    assert records[0].city == "Dayton"


def test_acm_keeps_only_reciprocal_flagged_museums():
    html = (FIXTURES / "acm_sample.html").read_text(encoding="utf-8")
    records = acm.parse_html(html)

    names = {r.name for r in records}
    assert "Please Touch Museum" in names
    assert "Kohl Children's Museum" in names
    assert "Non-Reciprocal Kids Museum" not in names  # data-reciprocal="false"
    assert len(records) == 2


def test_acm_sets_uniform_benefit_and_party_size():
    html = (FIXTURES / "acm_sample.html").read_text(encoding="utf-8")
    ptm = next(r for r in acm.parse_html(html) if r.name == "Please Touch Museum")
    assert ptm.program == "ACM"
    assert ptm.benefit == "discount_50"
    assert ptm.admits == 6
    assert ptm.city == "Philadelphia" and ptm.state == "PA"
    assert ptm.website == "https://www.pleasetouchmuseum.org"
    assert ptm.id == "please-touch-museum-philadelphia-pa"


def test_records_serialize_with_id():
    html = (FIXTURES / "acm_sample.html").read_text(encoding="utf-8")
    d = acm.parse_html(html)[0].to_dict()
    assert d["id"] and d["program"] == "ACM" and "raw" in d
