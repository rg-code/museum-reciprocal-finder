"""Tests for the AZA adapter, against rows from the real 2026-27 reciprocity list.

The fixture is the tab-separated extract that build.py writes next to a dropped
PDF (aza.extract_pdf_text); parsing it needs no network and no PDF.
"""
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import pytest  # noqa: E402

import aza  # noqa: E402


@pytest.fixture(scope="module")
def by_name():
    records = aza.parse_text((FIXTURES / "aza_sample.txt").read_text(encoding="utf-8"))
    return {r.name: r for r in records}


def test_only_us_rows_and_state_carries_down(by_name):
    assert "Toronto Zoo" not in by_name                 # CANADA section
    assert "Africam Safari Park" not in by_name         # MEXICO section
    assert all(r.program == "AZA" and r.source == "aza" for r in by_name.values())
    # "Idaho Falls" row has a blank State cell: it inherits ID from the row above.
    assert by_name["Idaho Falls Zoo at Tautphaus Park"].state == "ID"
    assert by_name["Smithsonian National Zoological Park"].state == "DC"
    assert by_name["Minnesota Zoological Garden"].city == "Apple Valley"


def test_in_kind_tiers_map_to_benefits(by_name):
    assert by_name["Birmingham Zoo"].benefit == "discount_50"
    assert by_name["Birmingham Zoo"].tier is None
    # 100% OR 50%: guaranteed 50%; the app upgrades to free for same-tier home zoos.
    zb = by_name["Idaho Falls Zoo at Tautphaus Park"]
    assert (zb.benefit, zb.tier) == ("discount_50", "100_or_50")
    lpz = by_name["Lincoln Park Zoo"]
    assert (lpz.benefit, lpz.tier) == ("free", "free_public")
    # Wrapped notes stay with their row.
    assert "gift shop" in lpz.raw
    assert by_name["The Wilds"].benefit == "discount_50"   # "50% off Open Air Safari"


def test_limit_sets_admits_only_for_admission(by_name):
    assert by_name["John G. Shedd Aquarium"].admits == 2
    assert by_name["Texas State Aquarium"].admits == 2
    # "FREE TO PUBLIC - 50% off Adventure Pass (Limit 4)": the limit is on the add-on.
    assert by_name["Saint Louis Zoo"].admits is None
    assert by_name["Saint Louis Zoo"].benefit == "free"


def test_fetch_refuses_because_aza_opts_out():
    with pytest.raises(RuntimeError, match="manual_drops/aza"):
        aza.fetch()


def test_every_row_gets_its_own_sections_state(by_name):
    expect = {"Lincoln Park Zoo": ("Chicago", "IL"), "Saint Louis Zoo": ("Saint Louis", "MO"),
              "The Wilds": ("Cumberland", "OH"), "Nashville Zoo, Inc.": ("Nashville", "TN"),
              "Texas State Aquarium": ("Corpus Christi", "TX"), "Alaska SeaLife Center": ("Seward", "AK")}
    assert {n: (by_name[n].city, by_name[n].state) for n in expect} == expect
