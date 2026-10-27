"""Private mode (docs/PRIVATE_MODE_PLAN.md): folder scan, keep marks, deletion limits, status, token; and that the
production app does not use any of it."""
import importlib
import json
import sys
from pathlib import Path

import pytest

from backend.common import folder as F
from backend.common.lineage import Lineage, fingerprint

ROOT = Path(__file__).resolve().parents[1]


def _ds(folder, name, size=100):
    d = folder / name
    d.mkdir()
    (d / "chunk-000000").write_bytes(b"x" * size)
    return d


@pytest.fixture
def strax(tmp_path):
    f = tmp_path / "strax_data"
    f.mkdir()
    _ds(f, "007591-event_basics-aaaaaaaaaa", 100)
    _ds(f, "007591-event_basics-bbbbbbbbbb", 200)
    _ds(f, "007591-peaks-cccccccccc_temp", 50)
    _ds(f, "007592-peak_basics-dddddddddd", 300)
    (f / "notes.json").write_text("{}")                 # other files: ignored
    (f / "some_folder").mkdir()                         # other folders: ignored
    return f


def test_scan(strax):
    ds = F.scan(strax)
    assert [d.name for d in ds if d.run == 7591 and d.dtype == "event_basics"]
    assert {d.name for d in ds} == {"007591-event_basics-aaaaaaaaaa", "007591-event_basics-bbbbbbbbbb",
                                    "007591-peaks-cccccccccc_temp", "007592-peak_basics-dddddddddd"}
    d = next(x for x in ds if x.temp)
    assert d.dtype == "peaks" and d.hash == "cccccccccc" and d.size == 50 and d.n_files == 1


def test_delete_preview_then_confirm_and_log(strax):
    pv = F.delete(strax, ["007591-event_basics-aaaaaaaaaa"])
    assert pv["size"] == 100 and pv["deleted"] == [] and (strax / "007591-event_basics-aaaaaaaaaa").exists()
    res = F.delete(strax, ["007591-event_basics-aaaaaaaaaa"], confirm=True)
    assert res["deleted"] == ["007591-event_basics-aaaaaaaaaa"]
    assert not (strax / "007591-event_basics-aaaaaaaaaa").exists()
    log = F.deletion_log(strax)
    assert log[0]["name"] == "007591-event_basics-aaaaaaaaaa" and log[0]["size"] == 100


def test_delete_refuses_outside_and_odd_names(strax, tmp_path):
    outside = tmp_path / "007591-event_basics-eeeeeeeeee"
    outside.mkdir()
    (strax / "007591-event_basics-ffffffffff").symlink_to(outside)        # a link out of the folder
    names = ["../007591-event_basics-eeeeeeeeee", "notes.json", "some_folder", "007591-event_basics-ffffffffff",
             "/etc", "007599-event_basics-0000000000"]
    res = F.delete(strax, names, confirm=True)
    assert res["deleted"] == [] and len(res["refused"]) == len(names)
    assert outside.exists() and (strax / "some_folder").exists()


def test_keep_blocks_deletion(strax):
    F.set_keep(strax, "007592-peak_basics-dddddddddd", True, "note X")
    assert F.load_keep(strax)["007592-peak_basics-dddddddddd"]["note"] == "note X"
    res = F.delete(strax, ["007592-peak_basics-dddddddddd"], confirm=True)
    assert res["deleted"] == [] and res["refused"][0]["reason"] == "marked keep"
    F.set_keep(strax, "007592-peak_basics-dddddddddd", False)
    assert F.delete(strax, ["007592-peak_basics-dddddddddd"], confirm=True)["deleted"]
    with pytest.raises(ValueError):
        F.set_keep(strax, "../x", True)


def test_status_from_cached_hashes(strax):
    providers = [{"name": "A", "kind": "amstrax"}, {"name": "B", "kind": "amstrax", "context": "other"}]
    lin = Lineage(strax, providers)
    lin.cache = {fingerprint(providers[0]): {"name": "A", "hashes": {"007591": {"event_basics": "aaaaaaaaaa"},
                                                                       "007592": {"peak_basics": None}}},
                 fingerprint(providers[1]): {"name": "B", "hashes": {"007591": {"event_basics": "zzzzzzzzzz"},
                                                                       "007592": {"peak_basics": None}}}}
    st = {d.name: lin.status(d) for d in F.scan(strax)}
    assert st["007591-event_basics-aaaaaaaaaa"] == {"status": "current", "current_for": ["A"]}
    assert st["007591-event_basics-bbbbbbbbbb"]["status"] == "outdated"      # made by A and B, other hashes
    assert st["007591-peaks-cccccccccc_temp"]["status"] == "incomplete"
    assert st["007592-peak_basics-dddddddddd"]["status"] == "unknown"        # neither provider makes it


def test_status_pending_until_computed(strax):
    lin = Lineage(strax, [{"name": "A", "kind": "amstrax"}])
    d = next(x for x in F.scan(strax) if x.dtype == "peak_basics")
    assert lin.status(d)["status"] == "pending"


def test_lineage_worker_function_provider(tmp_path):
    """The worker loads a provider file in its own process and reports null for what it cannot make."""
    from backend.common.lineage import run_worker
    (tmp_path / "prov.py").write_text(
        "class K:\n    def __init__(self, h): self.lineage_hash = h\n"
        "class St:\n    def __init__(self, run): self.run = run\n"
        "    def key_for(self, run, t):\n"
        "        if t != 'event_basics': raise KeyError(t)\n"
        "        return K('h' + run[-4:])\n"
        "def ctx(run):\n    if run == '000001': raise KeyError('not in my runs')\n    return St(run)\n")
    res = run_worker({"kind": "function", "path": str(tmp_path / "prov.py"), "call": "ctx", "args": ["{run}"]},
                     [["007591", ["event_basics", "peaks"]], ["000001", ["event_basics"]]])
    assert res["hashes"]["007591"] == {"event_basics": "h7591", "peaks": None}
    assert res["hashes"]["000001"] == {"event_basics": None} and "not in my runs" in res["errors"]["000001"]
    res = run_worker({"kind": "function", "path": str(tmp_path / "prov.py"), "call": "ctx", "args": ["{run}"],
                      "runs": [990000, 999999]}, [["007591", ["event_basics"]], ["990016", ["event_basics"]]])
    assert res["hashes"] == {"007591": {"event_basics": None}, "990016": {"event_basics": "h0016"}}


@pytest.fixture
def client(strax, tmp_path, monkeypatch):
    s = tmp_path / "private.json"
    s.write_text(json.dumps({"strax_folder": str(strax), "token": "secret-token", "contexts": []}))
    monkeypatch.setenv("XAMS_PRIVATE_SETTINGS", str(s))
    sys.modules.pop("v2.private_app", None)
    mod = importlib.import_module("v2.private_app")
    monkeypatch.setattr(mod.view, "rundocs", lambda runs: {r: {} for r in runs})
    return mod.app.test_client()


def test_token_required(client):
    assert client.get("/api/runs").status_code == 403
    assert client.get("/api/runs?token=wrong").status_code == 403
    r = client.get("/api/runs?token=secret-token")
    assert r.status_code == 200 and "xams_private_token" in r.headers.get("Set-Cookie", "")
    assert [x["run"] for x in r.get_json()["runs"]] == [7592, 7591]
    assert client.get("/api/runs").status_code == 200                       # cookie from now on
    r = client.get("/?token=secret-token")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")      # token out of the address


def test_token_not_in_request_log(client):              # client: the app module with test settings
    import logging
    from v2.private_app import _HideToken
    rec = logging.LogRecord("werkzeug", 20, "", 0, '%s - "%s" %s', ("127.0.0.1", "GET /?token=abc123&x=1 HTTP/1.1", 200), None)
    _HideToken().filter(rec)
    assert "abc123" not in rec.getMessage() and "token=***" in rec.getMessage()


def test_api_delete_outdated_preview(client):
    client.get("/?token=secret-token")
    pv = client.post("/api/delete-outdated", json={"incomplete": True}).get_json()
    assert [x["name"] for x in pv["delete"]] == ["007591-peaks-cccccccccc_temp"]   # no providers: nothing outdated
    assert pv["deleted"] == []


def test_production_app_does_not_use_private_settings():
    src = (ROOT / "v2" / "app.py").read_text()
    assert "backend.private" not in src and "private_app" not in src


# ------------------------------------------------------------------ what changed (plan 3.3)
OLD = {"peaks": ["Peaks", "1.0", {"a": [3, 20]}],
       "peak_positions": ["PeakPositions", "1.2.26", {"pos_rec_params": "file://pos_rec_params?filename=pos_rec_params_v0.json&x=1",
                                                       "default_reconstruction_algorithm": "corr"}],
       "event_basics": ["EventBasics", "1.6", {}]}
NEW = {"peaks": ["Peaks", "1.0", {"a": (3, 20)}],                                   # tuple: no change
       "peak_positions": ["PeakPositions", "2.1.0", {"pos_rec_map": "file://pos_rec_map?filename=pos_rec_map_v1.json"}],
       "event_basics": ["EventBasics", "1.7", {}]}


def test_diff_own_and_through():
    from backend.common import whatchanged as W
    d = W.diff(OLD, NEW, "event_basics")
    assert d["own"] and d["through"] == ["peak_positions"]
    pp = next(c for c in d["changes"] if c["dtype"] == "peak_positions")
    assert pp["version"] == ["1.2.26", "2.1.0"]
    assert pp["options"]["pos_rec_map"][0] is None and pp["options"]["default_reconstruction_algorithm"] == ["corr", None]
    assert not any(c["dtype"] == "peaks" for c in d["changes"])
    labs = W.labels(d)
    assert "PeakPositions 1.2.26 → 2.1.0" in labs and "EventBasics 1.6 → 1.7" in labs
    assert "PeakPositions: pos_rec_params pos_rec_params_v0.json → —" in labs
    sub = lambda lin: {k: v for k, v in lin.items() if k != "event_basics"}        # the lineage of peak_positions
    d2 = W.diff(sub(OLD), sub(NEW), "peak_positions")                              # same label for both data sets
    assert "PeakPositions 1.2.26 → 2.1.0" in W.labels(d2) and not d2["through"]


def test_diff_new_and_gone():
    from backend.common import whatchanged as W
    d = W.diff({"a": ["A", "1", {}]}, {"b": ["B", "2", {}]}, "b")
    assert {c["kind"] for c in d["changes"]} == {"new", "gone"}


def test_stored_lineage(strax):
    from backend.common import whatchanged as W
    name = "007591-event_basics-aaaaaaaaaa"
    (strax / name / "event_basics-aaaaaaaaaa-metadata.json").write_text(json.dumps({"lineage": OLD}))
    assert W.stored_lineage(strax, name) == OLD


def test_worker_lineage_mode(tmp_path):
    from backend.common.lineage import run_worker
    (tmp_path / "prov.py").write_text(
        "class K:\n    lineage_hash = 'h'\n    lineage = {'event_basics': ['EventBasics', '1.7', {'x': (1, 2)}]}\n"
        "class St:\n    def key_for(self, run, t): return K()\n"
        "def ctx(run): return St()\n")
    res = run_worker({"kind": "function", "path": str(tmp_path / "prov.py"), "call": "ctx", "args": ["{run}"]},
                     [["007591", ["event_basics"]]], want="lineage")
    assert res["hashes"]["007591"]["event_basics"] == {"event_basics": ["EventBasics", "1.7", {"x": [1, 2]}]}


def test_api_why(client, strax):
    from backend.common.lineage import fingerprint
    import v2.private_app as A
    name = "007591-event_basics-bbbbbbbbbb"
    (strax / name / "event_basics-bbbbbbbbbb-metadata.json").write_text(json.dumps({"lineage": OLD}))
    prov = {"name": "SR", "kind": "amstrax"}
    A.view.lineage.providers = [prov]
    A.view.lineage.cache = {fingerprint(prov): {"name": "SR", "errors": {},
                                           "hashes": {"007591": {"event_basics": "aaaaaaaaaa", "peaks": None},
                                                      "007592": {"peak_basics": None}},
                                           "lineages": {"007591": {"event_basics": NEW}}}}
    client.get("/?token=secret-token")
    w = client.get(f"/api/dataset/{name}/why").get_json()
    assert w["status"] == "outdated" and w["why"]["providers"][0]["through"] == ["peak_positions"]
    row = next(d for d in client.get("/api/run/7591").get_json()["datasets"] if d["name"] == name)
    assert "PeakPositions 1.2.26 → 2.1.0" in row["why_labels"]                  # full rows in the run panel
    slim = next(d for r in client.get("/api/runs").get_json()["runs"] for d in r["datasets"] if d["id"] == name)
    assert set(slim) <= {"id", "dtype", "hash", "status", "current_for", "keep", "size", "raw", "temp"}   # list: slim
    cur = client.get("/api/dataset/007591-event_basics-aaaaaaaaaa/why").get_json()
    assert cur["status"] == "current" and cur["why"] is None


def test_kind_tabs(client, strax):
    _ds(strax, "990016-peaks-gggggggggg", 10)
    client.get("/?token=secret-token")
    runs = lambda k: [x["run"] for x in client.get(f"/api/runs?kind={k}").get_json()["runs"]]
    assert runs("data") == [7592, 7591] and runs("mc") == [990016]
    assert client.get("/api/runs?kind=mc").get_json()["totals"]["n_datasets"] == 1
    assert 990016 in runs("all")


def test_worker_shared_context_and_types(tmp_path):
    """A provider without {run} makes one context for all runs; "types" limits the data types it judges."""
    from backend.common.lineage import run_worker
    (tmp_path / "prov.py").write_text(
        "N = [0]\n"
        "class K:\n    def __init__(self, h): self.lineage_hash = h\n"
        "class St:\n    def __init__(self): N[0] += 1; self.n = N[0]\n"
        "    def key_for(self, run, t): return K(f'{t[:3]}{self.n}')\n"
        "def ctx(): return St()\n")
    res = run_worker({"kind": "function", "path": str(tmp_path / "prov.py"), "call": "ctx", "args": [],
                      "types": ["records_led"]},
                     [["007591", ["records_led", "peaks"]], ["007592", ["records_led"]]])
    assert res["hashes"]["007591"] == {"records_led": "rec1", "peaks": None}
    assert res["hashes"]["007592"] == {"records_led": "rec1"}                      # the same context: made once
