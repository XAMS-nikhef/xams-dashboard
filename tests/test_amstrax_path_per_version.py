"""A corrections version processed with another amstrax snapshot (PROD6 with amstrax_versioned/v11) is judged with that
snapshot: provider key amstrax_path, set per version by XAMS_DASH_AMSTRAX_PATHS."""
import json
import subprocess
import sys

from backend.common import lineage as L
from backend.common.profile import production_providers


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


def test_providers_get_path_per_version(monkeypatch, tmp_path):
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD6,PROD5")
    monkeypatch.setenv("XAMS_DASH_AMSTRAX_PATHS", "PROD6=/sw/amstrax_versioned/v11")
    ps = {p["name"]: p for p in production_providers(tmp_path)}
    assert ps["PROD6"]["amstrax_path"] == "/sw/amstrax_versioned/v11" and "amstrax_path" not in ps["PROD5"]
