"""Corrections versions and the amstrax that made them come from the run database (data[] entries: corrections_version,
amstrax_path): a new production (PROD6 with amstrax_versioned/v11) shows up by itself, each version judged with its
own amstrax snapshot."""
import datetime as dt
import json
import subprocess
import sys

import mongomock

from backend.common import lineage as L
from backend.common.profile import Profile, production_providers, versions_from_rundb


def _fake_amstrax(root, tag):
    pkg = root / "amstrax"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "class _K:\n"
        "    def __init__(self, t): self.lineage_hash = '%s-' + t; self.lineage = {}\n"
        "class _St:\n"
        "    def key_for(self, run, t): return _K(t)\n"
        "class contexts:\n"
        "    @staticmethod\n"
        "    def xams(**kw): return _St()\n" % tag)
    return root


def _rundb(v10, v11):
    now = dt.datetime.utcnow()
    c = mongomock.MongoClient()["run"]["runs_gas"]
    c.insert_one({"number": 7826, "data": [
        {"type": "events", "corrections_version": "PROD5", "amstrax_path": str(v10), "time": now - dt.timedelta(days=17)},
        {"type": "events", "corrections_version": "PROD5", "amstrax_path": "/old/v9", "time": now - dt.timedelta(days=18)},
        {"type": "events", "corrections_version": "PROD6", "amstrax_path": str(v11) + "/", "time": now - dt.timedelta(hours=1)},
        {"type": "events", "corrections_version": "ONLINE", "time": now - dt.timedelta(days=20)},
        {"type": "events", "corrections_version": "v0", "amstrax_path": "/x/vTEST0", "time": now - dt.timedelta(days=400)},
        {"type": "live", "time": now}]})
    return c


def test_worker_imports_amstrax_from_path(tmp_path):
    root = _fake_amstrax(tmp_path / "v11", "v11")
    prov = {"kind": "amstrax", "context": "xams", "kwargs": {}, "amstrax_path": str(root)}
    r = subprocess.run([sys.executable, str(L.WORKER)], input=json.dumps({"provider": prov, "items": [["007833", ["events"]]]}),
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["hashes"]["007833"]["events"] == "v11-events"


def test_code_signature_of_path(tmp_path):
    root = _fake_amstrax(tmp_path / "v11", "v11")
    sig = L.code_signature({"kind": "amstrax", "amstrax_path": str(root)})
    assert sig[0] == str(root / "amstrax") and sig[1] == 1


def test_versions_from_rundb(tmp_path):
    v10, v11 = _fake_amstrax(tmp_path / "v10", "v10"), _fake_amstrax(tmp_path / "v11", "v11")
    found = versions_from_rundb(90, coll=_rundb(v10, v11))
    assert found == [("PROD6", str(v11) + "/"), ("PROD5", str(v10)), ("ONLINE", None)]      # newest first; v0 too old


def test_providers_from_rundb_plus_env(monkeypatch, tmp_path):
    v10, v11 = _fake_amstrax(tmp_path / "v10", "v10"), _fake_amstrax(tmp_path / "v11", "v11")
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD5,v4")
    monkeypatch.delenv("XAMS_DASH_AMSTRAX_PATHS", raising=False)
    ps = production_providers(tmp_path, versions_from_rundb(90, coll=_rundb(v10, v11)))
    by = {p["name"]: p for p in ps}
    assert [p["name"] for p in ps][:4] == ["PROD6", "PROD5", "ONLINE", "v4"]
    assert by["PROD6"]["amstrax_path"] == str(v11) and by["PROD5"]["amstrax_path"] == str(v10)
    assert "amstrax_path" not in by["ONLINE"] and "amstrax_path" not in by["v4"]           # the dashboard's own amstrax
    monkeypatch.setenv("XAMS_DASH_AMSTRAX_PATHS", f"PROD5={v11}")                           # override
    assert {p["name"]: p for p in production_providers(tmp_path, [("PROD5", str(v10))])}["PROD5"]["amstrax_path"] == str(v11)


def test_rundb_down_keeps_env_list(monkeypatch, tmp_path):
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD5,v4")

    class Broken:
        def aggregate(self, *a):
            raise RuntimeError("no db")
    assert versions_from_rundb(90, coll=Broken()) is None
    assert [p["name"] for p in production_providers(tmp_path, [])][:2] == ["PROD5", "v4"]


def test_dataview_picks_up_new_version(tmp_path, monkeypatch):
    from v2 import dataview as DV
    (tmp_path / "p").mkdir()
    provs = [[{"name": "PROD5", "kind": "amstrax"}]]
    p = Profile(name="production", title="t", locations=[], state_dir=tmp_path, providers=list(provs[0]),
                refresh_providers=lambda: provs[0])
    v = DV.DataView(p)
    v.lineage.start = lambda *a, **k: None
    v.rows()
    assert [x["name"] for x in v.lineage.providers] == ["PROD5"]
    provs[0] = [{"name": "PROD6", "kind": "amstrax"}, {"name": "PROD5", "kind": "amstrax"}]
    v.rows()
    assert [x["name"] for x in v.lineage.providers] == ["PROD5"]                       # within PROVIDERS_TTL: unchanged
    v._providers_checked -= DV.PROVIDERS_TTL
    ver = v.lineage.version
    v.rows()
    assert [x["name"] for x in v.lineage.providers] == ["PROD6", "PROD5"] and p.providers == provs[0]
    assert v.lineage.version > ver


def test_failing_provider_does_not_stop_others(tmp_path, monkeypatch):
    lin = L.Lineage(tmp_path, [{"name": "bad", "kind": "amstrax"}, {"name": "good", "kind": "amstrax"}])
    monkeypatch.setattr(L, "run_worker", lambda p, items, **k: {"fatal": "ImportError"} if p["name"] == "bad"
                        else {"hashes": {r: {t: "h" for t in ts} for r, ts in items}, "errors": {}})
    monkeypatch.setattr(L, "corrections_signature", lambda v: None)
    lin._hashes([(0, "fpbad", {"007826": ["events"]}), (1, "fpgood", {"007826": ["events"]})])
    assert lin.cache["fpgood"]["hashes"]["007826"]["events"] == "h" and "ImportError" in lin.state["error"]
