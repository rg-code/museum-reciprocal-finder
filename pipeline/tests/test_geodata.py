"""Tests for the Census gazetteer parsers in geodata.py (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geodata  # noqa: E402

# Real gazetteer shape: tab-separated, and the last header carries trailing spaces.
SAMPLE = (
    "GEOID\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG                                                                                                               \n"
    "64111\t8214452\t0\t3.172\t0.000\t39.056390\t-94.592896\n"
    "00601\t166847909\t799292\t64.42\t0.309\t18.180555\t-66.749961\n"
    "02114\t1463380\t276393\t0.565\t0.107\t42.361292\t-71.067800  \n"
)


def test_parse_gazetteer_maps_zip_to_rounded_lat_lng():
    z = geodata.parse_gazetteer(SAMPLE)
    assert z == {
        "00601": [18.181, -66.75],
        "02114": [42.361, -71.068],
        "64111": [39.056, -94.593],
    }
    assert list(z) == sorted(z)  # stable, diff-friendly output


def test_parse_gazetteer_handles_2026_pipe_format():
    text = (
        "GEOID|GEOIDFQ|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
        "00601|860Z200US00601|166744424|795116|64.38|0.307|18.180621|-66.749931\n"
    )
    assert geodata.parse_gazetteer(text) == {"00601": [18.181, -66.75]}


PLACES = (
    "USPS|GEOID|GEOIDFQ|ANSICODE|NAME|LSAD|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
    "MO|2965000|x|x|St. Louis city|25|A|160343174|10|61.9|0|38.635699|-90.244582\n"
    "TN|4752006|x|x|Nashville-Davidson metropolitan government (balance)|00|A|1231000000|1|475|1|36.171800|-86.785000\n"
    "HI|1571550|x|x|Urban Honolulu CDP|57|S|156900000|1|60|1|21.325800|-157.845000\n"
    "KY|2148006|x|x|Louisville/Jefferson County metro government (balance)|00|A|857000000|1|330|1|38.170000|-85.650000\n"
    "KY|2148000|x|x|Louisville city|25|F|0|0|0|0|38.200000|-85.700000\n"
    "PA|4200100|x|x|Aaronsburg CDP|57|S|1000|0|0|0|40.900000|-77.400000\n"
    "PA|4200101|x|x|Aaronsburg borough|21|A|500|0|0|0|40.910000|-77.410000\n"
    "CA|0667000|x|x|San Francisco city|25|A|121400000|479100000|46.9|185|37.727239|-123.032229\n"
    "AK|0203000|x|x|Anchorage municipality|37|A|4420000000|500000000|1706|193|61.177549|-149.274354\n"
)


def test_parse_places_strips_descriptors_and_keys_by_city_state():
    p = geodata.parse_places(PLACES)
    assert p["st louis, mo"] == [38.636, -90.245]
    assert p["nashville, tn"] == [36.172, -86.785]            # "-Davidson ... (balance)"
    assert p["honolulu, hi"] == [21.326, -157.845]            # "Urban Honolulu CDP"
    assert p["louisville, ky"] == [38.2, -85.7]                # real place beats the metro alias
    assert p["aaronsburg, pa"] == [40.91, -77.41]              # incorporated beats CDP
    assert geodata.place_key("Saint Louis", "MO") == "st louis, mo"
    # Internal point unusable (mostly water / 1,700 sq mi): the name is kept
    # (it's a real city) but with no point, so geocoding falls back to Nominatim.
    assert p["san francisco, ca"] is None and p["anchorage, ak"] is None


COUSUBS = (
    "USPS|GEOID|GEOIDFQ|ANSICODE|NAME|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
    "MA|2502729|x|x|Harvard town|A|68000000|2000000|26|1|42.504256|-71.588512\n"
    "NY|3604710|x|x|Brooklyn borough|G|179000000|70000000|69|27|40.635045|-73.950640\n"
    "MI|2600001|x|x|Bloomfield township|A|90000000|0|35|0|43.902372|-82.828401\n"
    "MI|2600002|x|x|Bloomfield charter township|A|66000000|0|25|0|42.577893|-83.274466\n"
    "TX|4800001|x|x|Abilene CCD|S|900000000|0|347|0|32.400000|-99.700000\n"
)


def test_parse_cousubs_keeps_towns_skips_ambiguous_and_statistical():
    c = geodata.parse_cousubs(COUSUBS)
    assert c["harvard, ma"] == [42.504, -71.589]     # New England town, not a Census place
    assert c["brooklyn, ny"] == [40.635, -73.951]    # NYC borough
    assert "bloomfield, mi" not in c                  # two Bloomfields in MI: ambiguous
    assert "abilene ccd, tx" not in c and "abilene, tx" not in c   # statistical division


def test_place_names_are_display_ready_with_points():
    names = {(n, st): (lat, lng) for n, st, lat, lng in geodata.place_names(PLACES, COUSUBS)}
    assert names[("St. Louis", "MO")] == (38.636, -90.245)          # Census spelling, not the lookup key
    assert names[("Nashville", "TN")] == (36.172, -86.785)          # alias of Nashville-Davidson
    assert names[("Harvard", "MA")] == (42.504, -71.589)            # New England town from cousubs
    assert names[("San Francisco", "CA")] == (None, None)           # kept for autocomplete, no usable point
    assert ("Louisville", "KY") in names and ("Louisville/Jefferson County metro government", "KY") not in names
    assert not any(n == "Bloomfield" and st == "MI" for n, st in names)   # ambiguous town
