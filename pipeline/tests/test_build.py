"""Tests for the build orchestrator (offline, via fixtures)."""
import json
import sys
from pathlib import Path

PIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(PIPE / "adapters"))

import build  # noqa: E402
from _common import Record  # noqa: E402


def test_collect_from_fixtures_astc_acm():
    records = build.collect(["astc", "acm"], from_fixtures=True)
    # 6 ASTC + 2 reciprocal ACM (non-reciprocal one is skipped by the adapter).
    programs = {r.program for r in records}
    assert programs == {"ASTC", "ACM"}
    assert sum(r.program == "ASTC" for r in records) == 6
    assert sum(r.program == "ACM" for r in records) == 2


def test_merge_combines_programs_for_same_museum():
    recs = [
        Record(program="NARM", name="Shared Museum", city="Kansas City", state="MO", source="narm"),
        Record(program="ROAM", name="Shared Museum", city="Kansas City", state="MO", source="roam"),
        Record(program="AZA", name="Some Zoo", city="San Diego", state="CA", benefit="free", source="aza"),
    ]
    museums = build.normalize_and_merge(recs)
    by_id = {m["id"]: m for m in museums}

    shared = by_id["shared-museum-kansas-city-mo"]
    assert set(shared["programs"]) == {"NARM", "ROAM"}
    assert sorted(shared["sources"]) == ["narm", "roam"]
    # benefit omitted when the record left it None (engine falls back to program default)
    assert "benefit" not in shared["programs"]["NARM"]

    zoo = by_id["some-zoo-san-diego-ca"]
    assert zoo["programs"]["AZA"]["benefit"] == "free"  # explicit benefit preserved


def test_program_counts_and_validate_pass():
    records = build.collect(["astc", "acm"], from_fixtures=True)
    museums = build.normalize_and_merge(records)
    counts = build.program_counts(museums)
    assert counts["ASTC"] == 6 and counts["ACM"] == 2
    # No previous meta -> guardrail has nothing to compare against -> passes.
    assert build.validate(museums, Path("/nonexistent")) == []


def test_validate_guardrail_flags_big_drop(tmp_path):
    # Seed a previous meta.json claiming ASTC had 100 members.
    (tmp_path / "meta.json").write_text(
        json.dumps({"counts": {"by_program": {"ASTC": 100}}}), encoding="utf-8"
    )
    museums = build.normalize_and_merge(
        [Record(program="ASTC", name="Only One", city="X", state="CA", source="astc")]
    )
    problems = build.validate(museums, tmp_path)
    assert any("ASTC" in p and "dropped" in p for p in problems)


def test_run_writes_museums_and_meta(tmp_path):
    stats = build.run(
        sources=["astc", "acm"], from_fixtures=True, geocode_enabled=False, out_dir=tmp_path
    )
    assert stats["museums"] == 8
    data = json.loads((tmp_path / "museums.json").read_text(encoding="utf-8"))
    assert len(data["museums"]) == 8
    assert all("programs" in m and "id" in m for m in data["museums"])

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["counts"]["museums"] == 8
    assert meta["counts"]["by_program"]["ASTC"] == 6
    # No network geocoding requested; ASTC rows stay null, but the 2 ACM rows
    # arrive pre-geocoded from their source.
    assert meta["geocoded"] == 2


def test_merge_matches_renamed_museum_in_same_city():
    # ASTC uses the current name, ACM the old one — same museum, one record.
    recs = [
        Record(program="ASTC", name="Lindsay Wildlife Experience", city="Walnut Creek", state="CA", source="astc"),
        Record(program="ACM", name="Lindsay Wildlife Museum", city="Walnut Creek", state="CA",
               lat=37.92342, lng=-122.07567, source="acm"),
        Record(program="ASTC", name="The DoSeum", city="San Antonio", state="TX", source="astc"),
        Record(program="ACM", name="The DoSeum, San Antonio's Museum for Kids", city="San Antonio", state="TX", source="acm"),
    ]
    museums = build.normalize_and_merge(recs)
    assert [(m["name"], sorted(m["programs"])) for m in museums] == [
        ("Lindsay Wildlife Experience", ["ACM", "ASTC"]),
        ("The DoSeum", ["ACM", "ASTC"]),
    ]
    assert museums[0]["lat"] == 37.92342  # precise ACM coords carried over


def test_merge_keeps_different_museums_apart():
    recs = [
        # Similar names, genuinely different museums.
        Record(program="ASTC", name="Florida Air Museum", city="Lakeland", state="FL", source="astc"),
        Record(program="ACM", name="Florida Children's Museum", city="Lakeland", state="FL", source="acm"),
        # Nothing distinctive left once the city and generic words go — never merged.
        Record(program="ASTC", name="Museum of Science, Boston", city="Boston", state="MA", source="astc"),
        Record(program="ACM", name="Boston Museum", city="Boston", state="MA", source="acm"),
        # Same distinctive words, but different cities.
        Record(program="ASTC", name="Discovery Museum", city="Acton", state="MA", source="astc"),
        Record(program="ACM", name="Discovery Museum", city="Bridgeport", state="CT", source="acm"),
    ]
    assert len(build.normalize_and_merge(recs)) == 6


def test_merge_uses_same_museum_aliases():
    recs = [
        Record(program="ASTC", name="Discovery Lab", city="Tulsa", state="OK", source="astc"),
        Record(program="ACM", name="Tulsa Children's Museum Discovery Lab", city="Tulsa", state="OK", source="acm"),
    ]
    (m,) = build.normalize_and_merge(recs)
    assert m["id"] == "discovery-lab-tulsa-ok" and sorted(m["programs"]) == ["ACM", "ASTC"]
