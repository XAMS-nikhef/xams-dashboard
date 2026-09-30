import backend.loadability as L


def test_uptodate_status(monkeypatch):
    monkeypatch.setattr(L, "_current_lineage", lambda run6, dtype, v=None: {"v4": "new4", None: "newonl"}.get(v))
    entries = [
        {"type": "event_info", "corrections_version": None, "lineage_hash": "old0"},
        {"type": "event_info", "corrections_version": "v3", "lineage_hash": "old3"},
        {"type": "event_info", "corrections_version": "v4", "lineage_hash": "old4"},
    ]
    assert L.processing_up_to_date(1, entries)["status"] == "outdated"
    assert L.processing_up_to_date(1, entries)["version"] == "v4"
    entries.append({"type": "event_info", "corrections_version": "v4", "lineage_hash": "new4"})
    assert L.processing_up_to_date(1, entries)["status"] == "current"
    assert L.processing_up_to_date(1, [{"type": "raw_records"}])["status"] == "none"
    assert L.processing_up_to_date(1, [{"type": "event_info", "lineage_hash": "newonl"}])["status"] == "current"
