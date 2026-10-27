"""Production profile of the data view (docs/UNIFIED_DASHBOARD_REPORT.md): deletion rules, several locations,
providers; without touching the real folders or the run database."""
from pathlib import Path

import pytest

from backend.common.lineage import fingerprint
from backend.common.profile import Location, Profile, production_providers
from v2.dataview import DataView


def _ds(folder, name, size=100):
    d = folder / name
    d.mkdir(parents=True)
    (d / "chunk-000000").write_bytes(b"x" * size)


@pytest.fixture
def view(tmp_path):
    proc, raw = tmp_path / "processed", tmp_path / "raw"
    _ds(proc, "007720-peak_positions-oldoldoldo")         # outdated
    _ds(proc, "007720-peak_positions-curcurcurc")         # current
    _ds(proc, "007720-event_basics-keptkeptke")           # outdated, kept
    _ds(raw, "007720-raw_records-rawrawrawr")             # raw, outdated
    _ds(raw, "007721-raw_records-rawrawrawr")             # raw, outdated, no live data on STBC
    prov = {"name": "PROD0", "kind": "amstrax"}
    deleted = []
    p = Profile(name="production", title="v3", state_dir=tmp_path / "state", providers=[prov],
                locations=[Location(proc, "xams_processed"), Location(raw, "xams_raw_records", raw=True)],
                delete_statuses=frozenset({"outdated", "incomplete"}),
                raw_rule=lambda d: None if d.run == 7720 else "no live data on STBC",
                on_delete=lambda d, loc: deleted.append((d.dtype, d.hash, loc.label)) or "data[] entry removed")
    v = DataView(p)
    v.lineage.cache = {fingerprint(prov): {"name": "PROD0", "errors": {}, "hashes": {
        "007720": {"peak_positions": "curcurcurc", "event_basics": "newnewnewn", "raw_records": "newrawnewr"},
        "007721": {"raw_records": "newrawnewr"}}}}
    v.lineage.start = lambda *a, **k: None
    v.lineage._lineage_todo = lambda ds: []
    (tmp_path / "state").mkdir()
    from backend.common import folder as F
    F.set_keep(tmp_path / "state", "007720-event_basics-keptkeptke", True, "paper")
    v.deleted = deleted
    return v


def test_ids_over_locations(view):
    ids = {r["id"]: r for r in view.rows()}
    assert "007720-peak_positions-oldoldoldo" in ids and "1:007720-raw_records-rawrawrawr" in ids
    assert ids["1:007720-raw_records-rawrawrawr"]["raw"] and ids["1:007720-raw_records-rawrawrawr"]["location"] == "xams_raw_records"


def test_production_delete_rules(view):
    pv = view.delete(["007720-peak_positions-oldoldoldo", "007720-peak_positions-curcurcurc",
                      "007720-event_basics-keptkeptke", "1:007720-raw_records-rawrawrawr",
                      "1:007721-raw_records-rawrawrawr", "../etc"])
    assert [x["name"] for x in pv["delete"]] == ["007720-peak_positions-oldoldoldo", "1:007720-raw_records-rawrawrawr"]
    assert "rebuilt from the live data" in pv["delete"][1]["note"]
    why = {x["name"]: x["reason"] for x in pv["refused"]}
    assert "only incomplete / outdated" in why["007720-peak_positions-curcurcurc"]
    assert why["007720-event_basics-keptkeptke"] == "marked keep"
    assert why["1:007721-raw_records-rawrawrawr"] == "no live data on STBC"
    assert pv["deleted"] == [] and view.deleted == []


def test_production_delete_confirm_calls_hook_and_logs(view, tmp_path):
    res = view.delete(["007720-peak_positions-oldoldoldo"], confirm=True)
    assert res["deleted"] == ["007720-peak_positions-oldoldoldo"]
    assert not (tmp_path / "processed" / "007720-peak_positions-oldoldoldo").exists()
    assert view.deleted == [("peak_positions", "oldoldoldo", "xams_processed")]
    log = (tmp_path / "state" / ".dashboard_deletions.log").read_text()
    assert "oldoldoldo" in log and "data[] entry removed" in log


def test_live_never(tmp_path):
    proc = tmp_path / "p"
    _ds(proc, "007720-live-aaaaaaaaaa")
    v = DataView(Profile(name="private", title="p", locations=[Location(proc, "p")], state_dir=tmp_path, providers=[]))
    v.lineage.start = lambda *a, **k: None
    res = v.delete(["007720-live-aaaaaaaaaa"], confirm=True)
    assert res["deleted"] == [] and res["refused"][0]["reason"] == "live data are never deleted"


def test_production_providers(monkeypatch, tmp_path):
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD0, v4")
    ps = production_providers(tmp_path)
    names = [p["name"] for p in ps]
    assert names == ["PROD0", "v4", "LED", "MC (MC1)"]
    assert ps[0]["kwargs"]["corrections_version"] == "PROD0" and ps[0]["runs"] == [0, 899999]
    assert ps[2]["types"] == ["records_led", "led_calibration"]
    assert Path(ps[3]["path"]).exists() and ps[3]["runs"] == [900000, 999999]


def test_bulk_outdated_never_raw(view, tmp_path):
    from flask import Flask
    from v2 import dataview as DV
    bp = DV.blueprint(view.p, base="")
    bp.view.lineage = view.lineage
    bp.view.rundocs = lambda runs: {r: {} for r in runs}
    app = Flask("t", template_folder=str(Path(DV.__file__).parent / "templates"))
    app.register_blueprint(bp)
    pv = app.test_client().post("/api/delete-outdated", json={"incomplete": True}).get_json()
    assert [x["name"] for x in pv["delete"]] == ["007720-peak_positions-oldoldoldo"]      # raw and kept left out


def _client(view, **hooks):
    from flask import Flask
    from v2 import dataview as DV
    for k, v in hooks.items():
        setattr(view.p, k, v)
    bp = DV.blueprint(view.p, base="")
    bp.view.lineage = view.lineage
    bp.view.rundocs = lambda runs: {r: {"processing": "done"} for r in runs}
    app = Flask("t", template_folder=str(Path(DV.__file__).parent / "templates"))
    app.register_blueprint(bp)
    return app.test_client()


def test_submit_through_host_app(view):
    calls = []
    c = _client(view, submit=lambda ids, t, v: calls.append((ids, t, v)) or {"submitted": len(ids), "results": []},
                submit_options=lambda: {"targets": ["event_info"], "corrections_versions": ["PROD0", "v4"],
                                        "default_version": "PROD0"},
                jobs=lambda: {7720: "running"})
    j = c.get("/api/runs").get_json()
    assert j["can_submit"] and next(r for r in j["runs"] if r["run"] == 7720)["job"] == "running"
    o = c.get("/api/submit-options").get_json()
    assert o["enabled"] and o["default_version"] == "PROD0"
    r = c.post("/api/submit", json={"run_ids": [7720], "targets": ["event_info"], "corrections_version": "v4"}).get_json()
    assert r["submitted"] == 1 and calls == [([7720], ["event_info"], "v4")]
    assert c.post("/api/submit", json={"run_ids": []}).status_code == 400


def test_no_submit_without_host(view):
    c = _client(view)
    assert c.get("/api/submit-options").get_json() == {"enabled": False}
    assert c.post("/api/submit", json={"run_ids": [7720]}).status_code == 404
    assert not c.get("/api/runs").get_json()["can_submit"]


def test_bulk_outdated_by_run_age(view):
    """'older than N days' looks at the run's start (run document), not at when the data set was written."""
    from flask import Flask
    from v2 import dataview as DV
    import datetime as _dt
    bp = DV.blueprint(view.p, base="")
    bp.view.lineage = view.lineage
    old = (_dt.datetime.now() - _dt.timedelta(days=400)).isoformat()
    bp.view.rundocs = lambda runs: {r: {"start": old} for r in runs}       # an old run, data written just now
    app = Flask("t", template_folder=str(Path(DV.__file__).parent / "templates"))
    app.register_blueprint(bp)
    c = app.test_client()
    assert [x["name"] for x in c.post("/api/delete-outdated", json={"older_than_days": 30}).get_json()["delete"]] \
        == ["007720-peak_positions-oldoldoldo"]
    bp.view.rundocs = lambda runs: {r: {"start": _dt.datetime.now().isoformat()} for r in runs}   # a run of today
    assert c.post("/api/delete-outdated", json={"older_than_days": 30}).get_json()["delete"] == []
