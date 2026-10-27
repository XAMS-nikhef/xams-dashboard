"""Private dashboard Process (backend/private/processing.py): provider and targets per run, job files, the job
limit with the waiting list, job state - with condor_q / condor_submit replaced."""
import json
import types

import pytest

from backend.common.lineage import fingerprint
from backend.common.profile import Location, Profile
from backend.private import processing as PP
from v2.dataview import DataView


def _ds(folder, name):
    d = folder / name
    d.mkdir(parents=True)
    (d / "chunk-000000").write_bytes(b"x")


@pytest.fixture
def env(tmp_path, monkeypatch):
    f = tmp_path / "strax"
    _ds(f, "007720-peak_positions-oldoldoldo")      # outdated for SR2
    _ds(f, "007720-peaks-curcurcurc")               # current
    _ds(f, "007721-peaks-xxxxxxxxxx")               # unknown (no provider knows 7721)
    _ds(f, "007722-event_basics-oldoldoldo")        # outdated
    sr3, sr2 = {"name": "SR3", "kind": "amstrax"}, {"name": "SR2", "kind": "amstrax", "python": "/py/bin/python"}
    v = DataView(Profile(name="private", title="p", locations=[Location(f, "strax")], state_dir=f, providers=[sr3, sr2]))
    v.lineage.cache = {
        fingerprint(sr3): {"name": "SR3", "errors": {}, "hashes": {"007720": {"peak_positions": None, "peaks": None},
                                                                   "007722": {"event_basics": None}}},
        fingerprint(sr2): {"name": "SR2", "errors": {}, "hashes": {"007720": {"peak_positions": "newnewnewn", "peaks": "curcurcurc"},
                                                                   "007722": {"event_basics": "newnewnewn"}}}}
    v.lineage.start = lambda *a, **k: None
    v.lineage._lineage_todo = lambda ds: []
    calls = {"submit": [], "q": ""}

    def fake_run(cmd, **kw):
        if cmd[0] == "condor_q":
            return types.SimpleNamespace(returncode=0, stdout=calls["q"], stderr="")
        calls["submit"].append(cmd[1])
        return types.SimpleNamespace(returncode=0, stdout="1 job(s) submitted", stderr="")
    monkeypatch.setattr(PP.subprocess, "run", fake_run)
    monkeypatch.setattr(PP.PrivateProcessing, "_loop", lambda self, s: None)
    return PP.PrivateProcessing(v, max_jobs=1), calls, f


def test_provider_and_outdated_targets(env):
    p, calls, f = env
    assert p.provider_for(7720)[1]["name"] == "SR2"                   # the one that makes the run's types
    assert p.targets_for(7720, [PP.OUTDATED]) == ["peak_positions"]  # outdated, not the current peaks
    with pytest.raises(ValueError):
        p.provider_for(7721)                                           # nobody knows the run


def test_submit_job_files_limit_and_queue(env):
    p, calls, f = env
    res = p.submit([7720, 7722, 7721], [PP.OUTDATED], "auto")
    st = {r["run_id"]: r["status"] for r in res["results"]}
    assert st == {7720: "submitted", 7722: "queued", 7721: "failed"}      # max_jobs 1: 7722 waits
    d = f / ".dashboard_jobs" / "007720"
    req = json.loads((d / "request.json").read_text())
    assert req["targets"] == ["peak_positions"] and req["provider"]["name"] == "SR2" and req["run"] == "007720"
    sub = (d / "job.sub").read_text()
    assert "batch_name     = xamsdash_007720" in sub and "request_memory = 8000MB" in sub
    assert "/py/bin/python" in (d / "job.sh").read_text() and "make_worker.py" in (d / "job.sh").read_text()
    assert calls["submit"] == [str(d / "job.sub")]
    calls["q"] = "xamsdash_007720 2\nxamssim_990018 2\n"               # our job running (other batches ignored)
    assert p.jobs() == {7720: "running", 7722: "queued"}
    assert p.process_queue() == []                                     # still full
    calls["q"] = ""
    done = p.process_queue()                                           # room: 7722 goes
    assert [r["run_id"] for r in done] == [7722] and p._queue() == []


def test_options(env):
    p, _, _ = env
    o = p.options()
    assert o["default_targets"] == [PP.OUTDATED] and o["corrections_versions"] == ["auto", "SR3", "SR2"]
