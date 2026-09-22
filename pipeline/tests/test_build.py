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
    # No geocoding requested -> coords stay null.
    assert meta["geocoded"] == 0
