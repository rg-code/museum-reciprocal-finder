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
    # No network geocoding requested, but the offline tables still apply: the 6
    # ASTC fixture cities are all in the Census place table, and the 2 ACM rows
    # arrive pre-geocoded from their source.
    assert meta["geocoded"] == 8


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


def test_manual_drop_feeds_a_source_that_is_not_scraped(tmp_path, monkeypatch):
    # AZA / Time Travelers opt out of automated access: fetch() refuses, and a
    # file dropped in manual_drops/<program>/ is used instead.
    (tmp_path / "aza").mkdir()
    (tmp_path / "aza" / "aza_2026.txt").write_text(
        (PIPE / "tests" / "fixtures" / "aza_sample.txt").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(build, "MANUAL", tmp_path)
    records = build.collect(["aza"])
    assert records and all(r.program == "AZA" for r in records)

    monkeypatch.setattr(build, "MANUAL", tmp_path / "empty")
    assert build.collect(["aza", "timetravelers"]) == []   # refused, not crashed


def test_manual_drop_pdf_is_extracted_to_txt_once_and_not_double_counted(tmp_path, monkeypatch):
    import aza
    drop = tmp_path / "aza"
    drop.mkdir()
    (drop / "aza-2026-27.pdf").write_bytes(b"%PDF-fake")
    fixture = (PIPE / "tests" / "fixtures" / "aza_sample.txt").read_text(encoding="utf-8")
    calls = []
    monkeypatch.setattr(aza, "extract_pdf_text", lambda b: calls.append(b) or fixture)
    monkeypatch.setattr(build, "MANUAL", tmp_path)

    first = build.collect(["aza"])
    assert (drop / "aza-2026-27.txt").read_text(encoding="utf-8") == fixture
    second = build.collect(["aza"])                # .txt now exists: PDF skipped
    assert len(calls) == 1 and first and len(second) == len(first)


def test_same_museum_prefix_and_alternate_forms():
    same = [
        ("Wexner Center for the Arts at Ohio State University", "Wexner Center for the Arts", "Columbus"),
        ("San Antonio Museum of Art (SAMA)", "San Antonio Museum of Art", "San Antonio"),
        ("Shaker Museum | Mount Lebanon", "Shaker Museum", "New Lebanon"),
        ("The Trustees/deCordova Sculpture Park and Museum", "deCordova Sculpture Park and Museum", "Lincoln"),
        ("Wichita Art Museum and Art Garden", "Wichita Art Museum", "Wichita"),
        ("Newfields (Indianapolis Museum of Art)", "Newfields", "Indianapolis"),
        ("Peace River Botanical & Sculpture Gardens Inc.", "Peace River Botanical and Sculpture Gardens", "Punta Gorda"),
        ("Telfair Museums", "Telfair Museum of Art", "Savannah"),
    ]
    different = [
        ("San Diego History Center", "San Diego Natural History Museum", "San Diego"),
        ("Museum of Utah", "Utah's Hogle Zoo", "Salt Lake City"),
        ("Museum of Contemporary Art Denver", "RedLine Contemporary Art Center", "Denver"),
        ("Museum of the Shenandoah Valley", "Shenandoah Valley Discovery Museum", "Winchester"),
        ("San Diego Museum of Art", "San Diego Museum of Man", "San Diego"),
        ("Chicago History Museum", "Chicago Children's Museum", "Chicago"),
    ]
    assert [x for x in same if not build.same_museum(*x)] == []
    assert [x for x in different if build.same_museum(*x)] == []


def test_merge_compares_against_every_name_already_merged():
    # ROAM's short name only matches NARM's, not ASTC's — it still joins the one museum.
    recs = [
        Record(program="ASTC", name="Roberson Museum", city="Binghamton", state="NY", source="astc"),
        Record(program="NARM", name="Roberson Museum and Science Center", city="Binghamton", state="NY", source="narm"),
        Record(program="ROAM", name="Roberson Museum & Science Center (RMSC)", city="Binghamton", state="NY", source="roam"),
    ]
    (m,) = build.normalize_and_merge(recs)
    assert sorted(m["programs"]) == ["ASTC", "NARM", "ROAM"]


def test_manual_drop_saved_html_page_becomes_a_txt_extract(tmp_path, monkeypatch):
    drop = tmp_path / "timetravelers"
    drop.mkdir()
    (drop / "list.htm").write_text(
        '<a class="v-list__tile--link"><div class="v-list__tile__title">Berman Museum of World History</div>'
        '<div class="v-list__tile__sub-title">840 Museum Drive Anniston, AL 36206</div>'
        '<div class="v-list__tile__sub-title">https://exploreamag.org/</div></a>', encoding="utf-8")
    monkeypatch.setattr(build, "MANUAL", tmp_path)
    (r,) = build.collect(["timetravelers"])
    assert (r.name, r.city, r.state) == ("Berman Museum of World History", "Anniston", "AL")
    assert (drop / "list.txt").exists()
    assert len(build.collect(["timetravelers"])) == 1        # .htm skipped once the .txt exists


def test_museum_kinds_from_names_and_programs():
    k = build.museum_kinds
    assert k(["Nelson-Atkins Museum of Art"], {"NARM": {}}) == ["art"]
    assert k(["Blanton Museum of Artat the University of Texas at Austin"], {"NARM": {}}) == ["art"]   # source typo
    assert k(["Arthur Ross House"], {"NARM": {}}) == ["history"]                                        # not "art"
    assert k(["Boston Children's Museum"], {"ACM": {}}) == ["children"]
    assert k(["San Diego Natural History Museum"], {"ASTC": {}}) == ["science", "nature"]              # not "history"
    assert k(["Turtle Bay Exploration Park"], {"ASTC": {}, "AHS": {}}) == ["science", "garden"]
    assert k(["Birmingham Zoo"], {"AZA": {}}) == ["zoo"]
    assert k(["Campbell House Museum"], {"TIMETRAVELERS": {}}) == ["history"]
    assert k(["Newfields"], {"NARM": {}}) == []                                                          # -> "Other"


def test_merged_museums_carry_kinds():
    (m,) = build.normalize_and_merge([
        Record(program="NARM", name="Newfields", city="Indianapolis", state="IN", source="narm"),
        Record(program="ROAM", name="Newfields (Indianapolis Museum of Art)", city="Indianapolis", state="IN", source="roam"),
    ])
    assert m["kinds"] == ["art"]        # the ROAM name supplies the kind


def test_museum_kinds_whole_word_and_culture_terms():
    k = build.museum_kinds
    assert k(["Eiteljorg Museum of American Indians & Western Art"], {}) == ["art", "history"]
    assert k(["Newfields (Indianapolis Museum of Art)"], {}) == ["art"]   # "Indian" only as a word
    assert k(["Delta Blues Museum"], {}) == ["history"]
    assert k(["Chinese American Museum"], {}) == ["history"]
    assert k(["Chicago Architecture Center"], {}) == ["art"]


def test_merge_treats_saint_and_st_as_the_same_city():
    (m,) = build.normalize_and_merge([
        Record(program="NARM", name="Carondelet Historical Society/Susan Blow Kindergarten Museum", city="St. Louis", state="MO", source="narm"),
        Record(program="ROAM", name="Carondelet History Museum / Susan Blow’s Kindergarten", city="Saint Louis", state="MO", source="roam"),
    ])
    assert sorted(m["programs"]) == ["NARM", "ROAM"] and m["city"] == "St. Louis"
