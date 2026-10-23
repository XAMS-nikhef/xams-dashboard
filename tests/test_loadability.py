"""Loadability of a run's datasets on disk (backend.loadability.scan_disk_availability, which replaced
assess_loadability): each dataset judged against the lineage the installed amstrax gives for the corrections version
recorded in the run DB. amstrax and the run DB are replaced by fakes, the disk by a temporary folder."""
from backend import loadability as L


def make(base, name, files=1):
    d = base / name
    d.mkdir()
    for i in range(files):
        (d / f"chunk_{i:06d}").write_bytes(b"x" * 1000)


def test_scan_disk_availability(tmp_path, monkeypatch):
    make(tmp_path, "007719-event_info-abc123")                   # current lineage for v4: loadable
    make(tmp_path, "007719-event_info-old999")                   # older product (v4 in the DB, other lineage)
    make(tmp_path, "007719-peak_basics-def456")                  # made in a v4 job, identical to the default lineage
    make(tmp_path, "007719-peaks-empty00", files=0)              # empty directory
    make(tmp_path, "007719-something_else-zzz")                  # not a target type: ignored
    make(tmp_path, "007720-event_info-abc123")                   # another run: ignored
    monkeypatch.setattr(L, "_storage_locations", lambda: [str(tmp_path)])
    monkeypatch.setattr(L, "_run_db_data_metadata", lambda run_id: {
        ("event_info", "abc123"): {"db_corrections_version": "v4"},
        ("event_info", "old999"): {"db_corrections_version": "v4"},
        ("peak_basics", "def456"): {"db_corrections_version": "v4"},
    })
    lineages = {("event_info", "v4"): "abc123", ("event_info", None): "dflt01",
                ("peak_basics", "v4"): "v4only", ("peak_basics", None): "def456",
                ("peaks", None): "empty00"}
    monkeypatch.setattr(L, "_expected", lambda run6, dtype, v: (lineages.get((dtype, v)), True))

    rows = {r["dataset_dir"]: r for r in L.scan_disk_availability(7719)}
    assert set(rows) == {"007719-event_info-abc123", "007719-event_info-old999", "007719-peak_basics-def456",
                         "007719-peaks-empty00"}
    assert rows["007719-event_info-abc123"]["loadable"] is True
    assert rows["007719-event_info-abc123"]["reason"] == "OK: loadable with corrections v4"
    assert rows["007719-event_info-old999"]["loadable"] is False
    assert rows["007719-event_info-old999"]["reason"].startswith("older product")
    assert rows["007719-peak_basics-def456"]["loadable"] is True               # matched via the default context
    assert "online" in rows["007719-peak_basics-def456"]["reason"]
    assert rows["007719-peaks-empty00"]["loadable"] is False
    assert rows["007719-peaks-empty00"]["reason"] == "directory exists but empty"


def test_helpers():
    assert L._parse_dataset_dirname("007375-event_info-abcdefghij") == {
        "run_prefix": "007375", "type": "event_info", "lineage_hash": "abcdefghij"}
    assert L._parse_dataset_dirname("007375-raw_records") == {}
    assert sorted(["v10", "online", "v2", "dev"], key=L._version_key) == ["online", "v2", "v10", "dev"]
    assert L._reason(3, True, None, None, "abc").startswith("could not build")
    assert L._reason(3, False, "v4", "new", "old").startswith("not registered in the run DB")


def test_scan_mc_run(tmp_path, monkeypatch):
    """Simulated runs: their own folders (raw records, processed), latest and truth reconstruction."""
    raw, proc = tmp_path / "mc_raw_records", tmp_path / "mc_processed"
    raw.mkdir(); proc.mkdir()
    make(raw, "900001-raw_records-y5oixg6qla")
    make(proc, "900001-event_info-latest1")
    make(proc, "900001-event_info-truth01")
    make(tmp_path, "900001-event_info-elsewh")                  # not in the MC folders: not looked at
    monkeypatch.setattr(L, "MC_RAW", str(raw))
    monkeypatch.setattr(L, "MC_PROCESSED", str(proc))
    monkeypatch.setattr(L, "_storage_locations", lambda: [str(tmp_path)])
    monkeypatch.setattr(L, "_run_db_data_metadata", lambda run_id: {
        ("raw_records", "y5oixg6qla"): {"db_corrections_version": "MC1"},
        ("event_info", "latest1"): {"db_corrections_version": "MC1"},
        ("event_info", "truth01"): {"db_corrections_version": "MC1"},
    })
    contexts = {"latest": {"raw_records": "y5oixg6qla", "event_info": "latest1"},
                "truth": {"raw_records": "y5oixg6qla", "event_info": "truth01"}}

    class Key:
        def __init__(self, h):
            self.lineage_hash = h

    class St:
        def __init__(self, use):
            self.use = use

        def key_for(self, run6, dtype):
            return Key(contexts[self.use][dtype])

        def is_stored(self, run6, dtype):
            return True
    monkeypatch.setattr(L, "_mc_context", lambda run6, use="latest": St(use))
    rows = {r["dataset_dir"]: r for r in L.scan_disk_availability(900001)}
    assert set(rows) == {"900001-raw_records-y5oixg6qla", "900001-event_info-latest1", "900001-event_info-truth01"}
    assert all(r["loadable"] for r in rows.values())
    assert rows["900001-event_info-truth01"]["reason"] == "OK: loadable with corrections MC1 (truth)"
