"""'Delete data' removes processed data only: raw_records* and live stay on disk and in the run document."""
import os

import mongomock

import backend.deletion_service as ds
from backend.mongo_service import MongoService


def test_disk_delete_keeps_raw(tmp_path, monkeypatch):
    raw, proc = tmp_path / "raw", tmp_path / "proc"
    rows = []
    for base, name, dtype in ((raw, "007719-raw_records-aaa", "raw_records"), (raw, "007719-raw_records_sipm-aaa", "raw_records_sipm"),
                              (raw, "007719-raw_records_ext-aaa", "raw_records_ext"), (proc, "007719-peaks-bbb", "peaks"),
                              (proc, "007719-event_info-ccc", "event_info")):
        (base / name).mkdir(parents=True)
        (base / name / "chunk").write_text("x")
        rows.append({"location": str(base), "dataset_dir": name, "type": dtype})
    monkeypatch.setattr(ds, "scan_disk_availability", lambda run_id: rows)
    out = ds.delete_run_disk_data(7719)
    assert sorted(os.listdir(raw)) == ["007719-raw_records-aaa", "007719-raw_records_ext-aaa", "007719-raw_records_sipm-aaa"]
    assert os.listdir(proc) == []
    assert len(out["deleted"]) == 2 and len(out["kept"]) == 3 and not out["errors"]


def test_db_delete_keeps_raw_and_live_entries():
    svc = MongoService.__new__(MongoService)
    svc.runs = mongomock.MongoClient().db.runs
    svc.runs.insert_one({"number": 7719, "data": [
        {"type": "live", "host": "daq"}, {"type": "live", "host": "stbc"}, {"type": "live", "host": "dcache"},
        {"type": "raw_records", "host": "wn"}, {"type": "peak_basics", "host": "wn"},
        {"type": "event_info", "host": "wn", "corrections_version": "v4"}]})
    res = svc.delete_run_data_entries(7719)
    doc = svc.runs.find_one({"number": 7719})
    assert res["modified"] == 1
    assert sorted((d["type"], d["host"]) for d in doc["data"]) == [
        ("live", "daq"), ("live", "dcache"), ("live", "stbc"), ("raw_records", "wn")]
    assert doc["processing_status"]["status"] == "deleted"
