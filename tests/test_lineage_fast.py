"""Lineage computation without per-batch start-up cost: one worker call per shared-context provider, lineages stored
once per distinct lineage."""
from types import SimpleNamespace

from backend.common import lineage as L


SHARED = {"kind": "amstrax", "context": "xams", "kwargs": {"output_folder": "/x"}}
PER_RUN = {"kind": "function", "path": "/x/xams_sr.py", "call": "context_for_runs", "args": [["{run}"]]}


def test_batch_size():
    assert L.batch_size(SHARED) == L.BATCH_SHARED
    assert L.batch_size(PER_RUN) == L.BATCH


def _lineage(tmp_path, monkeypatch, provider, lin_of=lambda r: {"event_basics": ["EventBasics", "1", {"x": 1}]}):
    calls = []

    def worker(p, items, timeout=3600, want="hash"):
        calls.append((want, len(items)))
        if want == "lineage":
            return {"hashes": {r: {t: lin_of(r) for t in ts} for r, ts in items}}
        return {"hashes": {r: {t: "newnewnewn" for t in ts} for r, ts in items}}
    monkeypatch.setattr(L, "run_worker", worker)
    lin = L.Lineage(tmp_path, [provider])
    ds = [SimpleNamespace(run=r, dtype="event_basics", hash="oldoldoldo", temp=False) for r in range(7000, 7300)]
    lin._run(lin._todo(ds), ds)
    return lin, ds, calls


def test_one_worker_call_per_phase_for_shared_provider(tmp_path, monkeypatch):
    lin, ds, calls = _lineage(tmp_path, monkeypatch, SHARED)
    assert calls == [("hash", 300), ("lineage", 300)]
    assert lin.status(ds[0])["status"] == "outdated"


def test_per_run_provider_keeps_small_batches(tmp_path, monkeypatch):
    _, _, calls = _lineage(tmp_path, monkeypatch, PER_RUN)
    assert [c for c in calls if c[0] == "hash"] == [("hash", 40)] * 7 + [("hash", 20)]


def test_lineages_stored_once(tmp_path, monkeypatch):
    lin, ds, _ = _lineage(tmp_path, monkeypatch, SHARED)
    entry = lin.cache[L.fingerprint(SHARED)]
    assert len(entry["lineage_store"]) == 1
    assert all(isinstance(v["event_basics"], str) for v in entry["lineages"].values())
    assert lin.current_lineages(ds[5]) == [("context 1", {"event_basics": ["EventBasics", "1", {"x": 1}]})]


def test_old_cache_with_inline_lineages_still_read(tmp_path, monkeypatch):
    lin, ds, _ = _lineage(tmp_path, monkeypatch, SHARED)
    entry = lin.cache[L.fingerprint(SHARED)]
    entry["lineages"]["007005"]["event_basics"] = {"inline": True}
    assert lin.current_lineages(ds[5]) == [("context 1", {"inline": True})]
