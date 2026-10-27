"""Private mode (docs/PRIVATE_MODE_PLAN.md): folder scan, keep marks, deletion limits, status, token; and that the
production app does not use any of it."""
import importlib
import json
import sys
from pathlib import Path

import pytest

from backend.private import folder as F
from backend.private.lineage import Lineage, fingerprint

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
    from backend.private.lineage import run_worker
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
    monkeypatch.setattr(mod, "_rundocs", lambda runs: {r: {} for r in runs})
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


def test_production_app_does_not_use_private_mode():
    src = (ROOT / "v2" / "app.py").read_text()
    assert "private" not in src
