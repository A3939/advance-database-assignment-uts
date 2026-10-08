import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.errors import ImportCancelled, NeedsInput, ValidationFailure
from arsia_pipeline.generic import process_generic, validate_profile


EXAMPLE = Path(__file__).parents[1] / "examples" / "wa-profile.json"


def make_file(root, name, header, rows):
    path = root / name
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return {"id":name,"name":name,"path":str(path),"size":path.stat().st_size,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def bundle(tmp_path):
    crashes = make_file(tmp_path,"wa-events.csv",["EVENT_ID","OCCURRED_ON","OUTCOME","DEATHS","INJURIES","UNIT_TOTAL"],
                        [["001","2020-01-05","Fatal","1","2","2"],
                         ["002","2021-04-06","Injury","0","1","1"],
                         ["003","2019-12-31","Injury","0","1","1"]])
    units = make_file(tmp_path,"wa-units.csv",["EVENT_ID","UNIT_ID","KIND"],
                     [["001","01","Car"],["001","02","Pedestrian"],["002","01","Car"],["003","01","Car"]])
    return [crashes,units],json.loads(EXAMPLE.read_text())


def run(tmp_path,bundle,profile=None,cancel=lambda:None):
    files, original = bundle
    work = tmp_path / "attempt"
    work.mkdir(exist_ok=True)
    return process_generic(files,work,{"profile":profile or original},lambda *a,**kw:None,cancel)


def test_independent_wa_oracle_and_complete_raw_retention(tmp_path,bundle):
    result = run(tmp_path,bundle)
    assert result["summary"] == {"crash_count":2,"fatal_crash_count":1,"fatalities":1,"casualties":4,
                                 "raw_record_count":7,"excluded_crash_count":1,"year_from":2020,"year_to":2024,"unit_count":3}
    assert result["trend"][0] == {"year":2020,"crash_count":1,"fatal_crash_count":1,"fatalities":1,"casualties":3}
    assert result["units"]["rows"] == [{"unit_type":"Car","count":2},{"unit_type":"Pedestrian","count":1}]
    canonical = [json.loads(line) for line in Path(result["canonical_path"]).read_text().splitlines()]
    assert {row["record_id"] for row in canonical} == {'["001"]','["002"]'}
    assert all(row["latitude"] is None for row in canonical)
    import sqlite3
    with sqlite3.connect(tmp_path/"attempt"/"staging.sqlite") as db:
        assert db.execute("SELECT count(*) FROM raw_rows").fetchone()[0] == 7
    assert [q["code"] for q in result["qa"] if q["status"]=="limited"] == ["QA07_LOCATION"]


def test_tas_different_layout_no_core_engine_change(tmp_path):
    file = make_file(tmp_path,"tas.csv",["ID_A","ID_B","EVENT_YEAR","EVENT_MONTH","CATEGORY","DEAD"],
                     [["01","1","2023","6","F","2"],["1","01","2024","","N",""]])
    profile = {"profile_version":"generic-v1","source_id":"tas_fixture","jurisdiction":"TAS",
               "source_name":"Tasmanian fictional test","publisher":"Test","source_evidence":"Hand-authored test","licence":"Synthetic",
               "confirmed":True,"analysis":{"year_from":2023,"year_to":2024},
               "resources":[{"role":"crash","filename":"tas.csv","key":["ID_A","ID_B"]}],
               "relations":[],"mapping":{"year":"EVENT_YEAR","month":"EVENT_MONTH","severity":"CATEGORY","fatalities":"DEAD"},
               "severity":{"F":{"code":"fatal","label":"Fatal","is_fatal_crash":True},
                           "N":{"code":"nonfatal","label":"Nonfatal","is_fatal_crash":False}}}
    result=run(tmp_path,([file],profile))
    assert result["summary"]["crash_count"]==2
    assert result["summary"]["fatalities"] is None
    assert result["summary"]["casualties"] is None
    assert result["summary"]["unit_count"] is None
    assert result["units"]["status"]=="unavailable"


def test_xlsx_generic_date_and_compound_identity(tmp_path):
    from openpyxl import Workbook
    book=Workbook(); sheet=book.active;sheet.title="Events"
    sheet.append(["crash","year","severity"]);sheet.append(["0005",2024,"Injury"])
    path=tmp_path/"events.xlsx";book.save(path)
    file={"id":"x","name":path.name,"path":str(path),"size":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    p=json.loads(EXAMPLE.read_text());p["resources"]=[{"role":"crash","filename":path.name,"sheet":"Events","key":["crash"]}]
    p["relations"]=[];p["mapping"]={"year":"year","severity":"severity"}
    r=run(tmp_path,([file],p))
    assert r["summary"]["crash_count"]==1
    assert json.loads(Path(r["canonical_path"]).read_text())["record_id"]=='["0005"]'


@pytest.mark.parametrize("case",["orphan","duplicate","outside_scope_duplicate","declared_count","unknown_severity","bad_date","negative_count","missing_key"])
def test_bad_data_blocks_publication(tmp_path,bundle,case):
    files,p=bundle
    if case=="orphan":
        files[1]=make_file(tmp_path,"wa-units.csv",["EVENT_ID","UNIT_ID","KIND"],[["MISSING","01","Car"]])
    else:
        rows=[["001","2020-01-05","Fatal","1","2","2"],["002","2021-04-06","Injury","0","1","1"],["003","2019-12-31","Injury","0","1","1"]]
        if case=="duplicate":rows.append(rows[0])
        if case=="outside_scope_duplicate":rows.append(rows[2])
        if case=="declared_count":rows[0][-1]="5"
        if case=="unknown_severity":rows[0][2]="Unreviewed"
        if case=="bad_date":rows[0][1]="01/02/2020"
        if case=="negative_count":rows[0][3]="-1"
        if case=="missing_key":rows[0][0]=""
        files[0]=make_file(tmp_path,"wa-events.csv",["EVENT_ID","OCCURRED_ON","OUTCOME","DEATHS","INJURIES","UNIT_TOTAL"],rows)
    with pytest.raises(ValidationFailure):run(tmp_path,(files,p))


def test_missing_file_needs_input(tmp_path,bundle):
    files,p=bundle
    with pytest.raises(NeedsInput,match="wa-units.csv"):
        run(tmp_path,(files[:1],p))


@pytest.mark.parametrize("mutate",[
    lambda p:p.update(confirmed=False),
    lambda p:p.update(source_id="official_vic"),
    lambda p:p.update(jurisdiction="NZ"),
    lambda p:p["resources"][0].update(filename="../../secret.csv"),
    lambda p:p["resources"][0].update(key=[]),
    lambda p:p["mapping"].update(python="eval()"),
    lambda p:p.update(relations=[]),
    lambda p:p["mapping"].update(date_format="%x"),
    lambda p:p.update(source_evidence=""),
    lambda p:p["severity"]["Fatal"].update(is_fatal_crash="true"),
])
def test_incomplete_or_unsafe_profile_cannot_execute(mutate):
    profile=json.loads(EXAMPLE.read_text());mutate(profile)
    with pytest.raises(NeedsInput):validate_profile(profile)


def test_fingerprint_changes_with_semantic_rule(tmp_path,bundle):
    result=run(tmp_path,bundle)
    other=tmp_path/"second";other.mkdir()
    profile=copy.deepcopy(bundle[1]);profile["severity"]["Injury"]["label"]="Revised source label"
    revised=run(other,bundle,profile)
    assert result["fingerprint"]!=revised["fingerprint"]


def test_cancellation_is_observed(tmp_path,bundle):
    def cancelled():raise ImportCancelled()
    with pytest.raises(ImportCancelled):run(tmp_path,bundle,cancel=cancelled)
