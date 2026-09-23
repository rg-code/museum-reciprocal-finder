"""Tests for the ZCTA gazetteer -> zip_centroids.json parser (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zip_centroids  # noqa: E402

# Real gazetteer shape: tab-separated, and the last header carries trailing spaces.
SAMPLE = (
    "GEOID\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG                                                                                                               \n"
    "64111\t8214452\t0\t3.172\t0.000\t39.056390\t-94.592896\n"
    "00601\t166847909\t799292\t64.42\t0.309\t18.180555\t-66.749961\n"
    "02114\t1463380\t276393\t0.565\t0.107\t42.361292\t-71.067800  \n"
)


def test_parse_gazetteer_maps_zip_to_rounded_lat_lng():
    z = zip_centroids.parse_gazetteer(SAMPLE)
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
    assert zip_centroids.parse_gazetteer(text) == {"00601": [18.181, -66.75]}
