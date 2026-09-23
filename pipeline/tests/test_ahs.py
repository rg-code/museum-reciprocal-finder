"""Golden-sample tests for the AHS Garden Network adapter.

The fixture is 14 real entries trimmed from the `js_data.locations` list embedded
in https://ahsgardening.org/ahs-garden-network/ (Sep 2026). No network.
Run:  pytest pipeline/tests/test_ahs.py
"""
import json
import sys
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ADAPTERS))

import ahs  # noqa: E402

SAMPLE = FIXTURES / "ahs_sample.json"


def _records():
    return ahs.parse_json(SAMPLE.read_text(encoding="utf-8"))


def _by_name():
    return {r.name: r for r in _records()}


def test_keeps_us_gardens_and_drops_foreign():
    records = _records()
    names = {r.name for r in records}
    # 14 entries: Toronto (ON), American Museum (UK), St. George Village (USVI)
    # and the Manitoba-side International Peace Garden entry are dropped.
    assert len(records) == 10
    assert "Toronto Botanical Garden" not in names
    assert "American Museum & Gardens" not in names
    assert "St. George Village Botanical Garden" not in names
    assert all(r.country == "US" for r in records)
    assert all(r.program == "AHS" and r.source == "ahs" for r in records)
    # The Peace Garden straddles the border: only the Dunseith, ND entry survives.
    peace = [r for r in records if r.name == "International Peace Garden"]
    assert len(peace) == 1 and peace[0].state == "ND" and peace[0].city == "Dunseith"


def test_address_coords_and_website():
    by = _by_name()
    adk = by["Adkins Arboretum"]
    assert (adk.city, adk.state, adk.zip) == ("Ridgely", "MD", "21660")  # full state name
    assert adk.lat == 38.9509 and adk.lng == -75.9355
    assert adk.website == "http://www.adkinsarboretum.org"
    assert adk.id == "adkins-arboretum-ridgely-md"

    # Name on the first address line; 2-letter state; double space before ZIP.
    cat = by["Catalina Island Conservancy – Wrigley Memorial & Botanic Garden"]
    assert (cat.city, cat.state, cat.zip) == ("Avalon", "CA", "90704")
    assert cat.website.startswith("https://catalinaconservancy.org/")

    for r in by.values():
        assert len(r.state) == 2
        assert r.zip and len(r.zip) == 5 and r.zip.isdigit()
        assert 18 < r.lat < 72 and -180 < r.lng < -65


def test_names_are_cleaned():
    by = _by_name()
    # Source name is "Imua\xa0Discovery Garden\xa0".
    imua = by["Imua Discovery Garden"]
    assert (imua.city, imua.state) == ("Kahului", "HI")
    # Mail-tracking redirect attrs are ignored; the real href is used.
    assert imua.website == "https://discoverimua.com/garden/"
    assert "George Washington’s American Horticultural Society" in by
    assert by["George Washington’s American Horticultural Society"].website is None


def test_benefits():
    by = _by_name()
    # Default free admission (Additional Benefits are extras) -> None.
    assert by["Adkins Arboretum"].benefit is None
    # Local Visitor Exception / parking notes don't change the benefit, but are kept in raw.
    airlie = by["Airlie Gardens"]
    assert airlie.benefit is None and "Local Visitor Exception" in airlie.raw
    assert by["Brooklyn Botanic Garden"].benefit is None
    assert "Parking Fee" in by["Brooklyn Botanic Garden"].raw
    # Partial benefit: 50% off.
    assert by["Texas Discovery Gardens"].benefit == "discount_50"
    # Explicit admit count.
    domes = by["Mitchell Park Horticultural Conservatory (The Domes)"]
    assert domes.admits == 2 and domes.benefit is None
    assert sum(1 for r in by.values() if r.benefit or r.admits) == 2


def test_accepts_page_html_and_js_data_shapes():
    locs = json.loads(SAMPLE.read_text(encoding="utf-8"))
    js_data = {"locations": json.dumps(locs), "ajax": "https://ahsgardening.org/wp-admin/admin-ajax.php"}
    page = ('<html><script id="custom-scripts-js-extra">\nvar js_data = '
            + json.dumps(js_data) + ";\n//# sourceURL=custom-scripts-js-extra\n</script></html>")
    expected = [r.to_dict() for r in _records()]
    assert [r.to_dict() for r in ahs.parse_json(page)] == expected
    assert [r.to_dict() for r in ahs.parse_json(js_data)] == expected
    assert [r.to_dict() for r in ahs.parse_json(locs)] == expected


def test_page_without_map_data_raises():
    try:
        ahs.parse_json("<html><body>redesigned</body></html>")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_fetch_uses_page_url_and_user_agent():
    page = ("<script>var js_data = " + json.dumps({"locations": SAMPLE.read_text(encoding="utf-8")})
            + ";\n</script>")

    class Resp:
        text = page

        def raise_for_status(self):
            pass

    class Sess:
        def get(self, url, timeout=None, headers=None):
            self.url, self.timeout, self.headers = url, timeout, headers
            return Resp()

    sess = Sess()
    records = ahs.fetch(sess)
    assert len(records) == 10
    assert sess.url == ahs.PAGE_URL and sess.timeout
    assert sess.headers["User-Agent"].startswith("museum-reciprocal-finder/0.2")


def test_local_visitor_exception_opts_the_garden_into_the_90_mile_rule():
    recs = ahs.parse_json((FIXTURES / "ahs_sample.json").read_text(encoding="utf-8"))
    flagged = [r for r in recs if "local visitor exception" in r.raw.lower()]
    assert flagged, "fixture should include a Local Visitor Exception garden"
    assert all(r.exclusion == {"radius_mi": 90, "anchors": ["residence"]} for r in flagged)
    assert all(r.exclusion is None for r in recs if r not in flagged)
