"""The lineage cache key changes when the amstrax code changes (amstrax 2 -> 3 kept old 'current' verdicts)."""
import os
import time

from backend.common import lineage as L


def test_fingerprint_follows_amstrax_code(tmp_path, monkeypatch):
    pkg = tmp_path / "amstrax"
    (pkg / "plugins").mkdir(parents=True)
    (pkg / "__init__.py").write_text("__version__ = '2.2.0'\n")
    (pkg / "plugins" / "events.py").write_text("x = 1\n")
    monkeypatch.setattr(L, "_amstrax_dir", lambda py: str(pkg))
    monkeypatch.setattr(L, "corrections_signature", lambda v: "same")
    prov = {"name": "PROD5", "kind": "amstrax", "context": "xams", "kwargs": {"corrections_version": "PROD5"}}
    a = L._fingerprint(prov)
    assert L._fingerprint(prov) == a                               # unchanged code: same key
    t = time.time() + 10
    (pkg / "plugins" / "event_cuts.py").write_text("y = 2\n")    # a new plugin file (amstrax update)
    os.utime(pkg / "plugins" / "event_cuts.py", (t, t))
    assert L._fingerprint(prov) != a
    assert L.code_signature({"kind": "function"}) is None
