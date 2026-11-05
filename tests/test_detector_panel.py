"""Detector tiles of the run page: start values from sc_snapshot, differences and fields (never from comments)."""
from backend.common import detector as D


def _snap(c, g, a, p=1.85):
    v = lambda x, u="V": {"value": x, "unit": u, "quality": "ok"}             # noqa: E731
    return {"time": "2026-11-03 16:09:42", "sc_config": "4021ee2",
            "values": {"hv_cathode_vmon": v(c), "hv_gate_vmon": v(g), "hv_anode_vmon": v(a),
                       "hv_anode_imon": v(0.22, "uA"), "pmain": v(p, "bar"), "tt401": v(-90, "C")}}


def test_start_tiles_run_8103():
    p = D.panel({"start": _snap(-1546.2, -1046.0, 2501.0), "end": _snap(-1500, -1000, 2400, 1.9)})
    t = {k: v for k, v, _ in p["tiles"]}
    assert t == {"drift field": "96.6", "extraction (liquid)": "3", "cathode": "-1546", "gate": "-1046",
                 "anode": "2501", "pressure": "1.85"}                         # start values only
    r = {k: v for k, v, _, _ in p["rows"]}
    assert r["ΔV anode − gate"] == "3547" and r["extraction field, gas"] == "5.87" and r["anode current"] == "0.22"
    assert r["temperature TT401"] == "-90" and p["which"] == "start" and not p["message"]


def test_end_when_no_start_and_missing():
    p = D.panel({"start": {"time": "x", "unavailable": "ssh timeout"}, "end": _snap(-1000, 0, 5000)})
    assert p["which"] == "end" and "values at the end" in p["message"]
    assert dict((k, v) for k, v, _ in p["tiles"])["extraction (liquid)"] == "4.22"     # 5 kV at 4 + 4 mm
    assert "no slow-control snapshot" in D.panel({})["message"]
    assert "unavailable at the start (ssh timeout)" in D.panel({"start": {"unavailable": "ssh timeout"}})["message"]
