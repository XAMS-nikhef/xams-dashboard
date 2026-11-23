"""Run page of a simulated run: run document from run.runs_mc or (private MC) the file next to the raw records."""
import json
import sys
import types

import pytest

from backend.common import mcrun as MC
from backend.common.profile import Location, Profile
from tests.test_dataview_production import _client, _ds
from v2.dataview import DataView

SUMMARY = {"state": {"state": "ma", "drift field [V/cm]": 96.5, "extraction field, gas [kV/cm]": 3.742},
           "voltages [V]": {"A": 2101, "G": -646, "C": -1146},
           "source": {"source": "cs137 @ t16", "position [mm]": [-122.7, -39.9, -33.0]},
           "physics": {"nest": {"widths": {"A_ER": 0.067}}}, "backfilled": "2026-11-23 from the config of that day"}


def _doc(summary=True):
    x = {"state": "ma", "source": "cs137 @ t16", "n_events": 10000000, "seed": 845, "run_name": "cs137_ma_t16",
         "made": {"$date": "2026-11-22T14:14:10.844Z"}, "detector": "xams_sr2026_3", "maps": {"drift": "bfe9ae997a31"},
         "corrections": {"truth": {"electron_drift_velocity": 0.000145814, "drift_time_gate": 6153.6,
                                   "drift_time_cathode": 40992.4, "elife": 1044000.0}}}
    if summary:
        x["summary"] = SUMMARY
    return {"number": 990078, "mode": "simulation (ma)", "tags": ["simulation", "cs137"],
            "comments": [{"comment": "xams-sim run 990078"}], "daq_config": {"big": 1}, "xamssim": x}


@pytest.fixture
def no_db(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("no database here")
    monkeypatch.setitem(sys.modules, "amstrax", types.SimpleNamespace(get_mongo_collection=fail, get_run_collection=fail))


@pytest.fixture
def view(tmp_path, no_db):
    proc, raw = tmp_path / "processed", tmp_path / "raw"
    _ds(proc, "990078-events-r46xn4gwhq")
    _ds(raw, "990078-raw_records-y5oixg6qla")
    (raw / "990078-metadata.json").write_text(json.dumps(_doc()))
    (tmp_path / "state").mkdir()
    p = Profile(name="private", title="private", state_dir=tmp_path / "state", providers=[],
                locations=[Location(proc, "mc_processed"), Location(raw, "mc_raw_records", raw=True)])
    v = DataView(p)
    v.lineage.start = lambda *a, **k: None
    return v


def test_groups_from_summary():
    g = MC.groups(json.loads(json.dumps(_doc()), object_hook=MC._hook))
    assert g["voltages [V]"]["A"] == "2101" and g["state"]["drift field [V/cm]"] == "96.5"
    assert g["source"]["position [mm]"] == "-122.7, -39.9, -33"
    assert g["physics"]["nest.widths.A_ER"] == "0.067"
    assert g["true corrections"]["drift velocity [mm/µs]"] == "1.458"
    assert g["true corrections"]["electron lifetime [µs]"] == "1044"


def test_groups_without_summary():
    g = MC.groups(_doc(summary=False))
    assert g["state"] == {"state": "ma", "detector": "xams_sr2026_3"} and "voltages [V]" not in g
    assert "made before" in MC.note(_doc(summary=False))


def test_private_mc_run_from_file(view):
    assert view.rundocs([990078])[990078]["source"] == "cs137 @ t16"          # no database: the file
    page = view.run_page(990078)
    facts = dict(page["facts"])
    assert facts["state"] == "ma" and facts["decays"] == "1e+07" and facts["made"] == "2026-11-22 14:14"
    assert page["detector_groups"]["voltages [V]"]["G"] == "-646"
    assert "summary added" in page["groups_note"]


def test_page_and_doc_api(view):
    c = _client(view)
    c.dv._mc_file = view._mc_file
    html = c.get("/run/990078").get_data(as_text=True)
    assert "voltages [V]" in html and "cs137 @ t16" in html and "summary added" in html
    d = c.get("/api/run/990078/doc").get_json()
    assert d["xamssim"]["state"] == "ma" and "daq_config" not in d


def test_data_run_unchanged(view):
    page = view.run_page(7720)
    assert page["groups_note"] == "start of the run (sc_snapshot)"
