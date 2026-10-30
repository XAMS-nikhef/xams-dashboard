"""The lineage fingerprint of an amstrax provider follows the content of its corrections version (ONLINE moves under
the same name), not only the version name."""
import json

from backend.common import lineage as L


def _fake_repo(monkeypatch, files):
    def fetch(url):
        key = url[len(L.CORRECTIONS_URL) + 1:]
        if key not in files:
            raise OSError(f"404 {key}")
        return files[key]
    monkeypatch.setattr(L, "_fetch", fetch)
    L._SIG.clear(); L._FP.clear()


def _repo(gains=b"[1]", width=150):
    return {"_global/_global_ONLINE.json": json.dumps({"gain_to_pe_array": "gain_to_pe_array_online.json",
                                                       "s1_max_width": width}).encode(),
            "gain_to_pe_array/gain_to_pe_array_online.json": gains}


PROV = {"kind": "amstrax", "context": "xams", "kwargs": {"output_folder": "/x", "corrections_version": "ONLINE"}}


def test_signature_changes_with_global_and_with_named_file(monkeypatch):
    _fake_repo(monkeypatch, _repo())
    a = L._fingerprint(PROV)
    _fake_repo(monkeypatch, _repo(width=200))                # setting in the _global file
    b = L._fingerprint(PROV)
    _fake_repo(monkeypatch, _repo(gains=b"[2]"))             # content of a named file, same name
    c = L._fingerprint(PROV)
    assert len({a, b, c}) == 3


def test_same_content_same_fingerprint(monkeypatch):
    _fake_repo(monkeypatch, _repo())
    a = L._fingerprint(PROV)
    _fake_repo(monkeypatch, _repo())
    assert L._fingerprint(PROV) == a


def test_fetch_error_keeps_last_signature(monkeypatch):
    _fake_repo(monkeypatch, _repo())
    a = L._fingerprint(PROV)
    L._SIG["ONLINE"] = (0.0, L._SIG["ONLINE"][1])           # expired
    monkeypatch.setattr(L, "_fetch", lambda url: (_ for _ in ()).throw(OSError("offline")))
    assert L._fingerprint(PROV) == a


def test_other_providers_untouched(monkeypatch):
    called = []
    monkeypatch.setattr(L, "_fetch", lambda url: called.append(url) or b"{}")
    L._SIG.clear()
    L._fingerprint({"kind": "function", "path": "/nonexistent/xams_sr.py", "call": "context_for_runs"})
    L._fingerprint({"kind": "amstrax", "context": "xams_led", "kwargs": {"output_folder": "/x"}})
    assert called == []
