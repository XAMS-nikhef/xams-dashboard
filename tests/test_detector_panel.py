"""Detector panel of the run page: sc_snapshot values, differences and fields (never from comments)."""
from backend.common import detector as D


def _snap(c, g, a, p=1.85):
    v = lambda x, u="V": {"value": x, "unit": u, "quality": "ok"}             # noqa: E731
    return {"time": "2026-11-03 16:09:42", "sc_config": "4021ee2",
            "values": {"hv_cathode_vmon": v(c), "hv_gate_vmon": v(g), "hv_anode_vmon": v(a),
                       "hv_anode_imon": v(0.22, "uA"), "pmain": v(p, "bar")}}


def test_fields_run_8103():
    p = D.panel({"start": _snap(-1546.2, -1046.0, 2501.0), "end": _snap(-1546.0, -1046.1, 2501.2, 1.86)})
    f = dict((r[0], r) for r in p["groups"]["Fields (uniform estimate)"])
    assert f["drift field"][1] == "96.6"                                       # 500.2 V / 5.18 cm = 96.56
    assert f["extraction field, liquid"][1] == "3"                             # 3547 V / 1.184 cm = 2.996 kV/cm
    assert f["extraction field, gas"][1] == "5.87"
    assert f["ΔV anode − gate"][1] == "3547"
    hv = dict((r[0], r) for r in p["groups"]["High voltage"])
    assert hv["anode"][1] == "2501" and "0.22" in hv["anode"][4]
    assert p["groups"]["Detector"][0][:3] == ("pressure", "1.85", "1.86")
    assert p["times"]["start"] == "2026-11-03 16:09:42" and not p["message"]


def test_missing_and_unavailable():
    assert "no slow-control snapshot" in D.panel({})["message"]
    p = D.panel({"start": {"time": "x", "unavailable": "ssh timeout"}})
    assert "start: slow control unavailable (ssh timeout)" in p["message"] and "end: no snapshot" in p["message"]


def test_old_extraction_reference():                                          # 5 kV at 4 + 4 mm: 4.2 kV/cm (2026-10-01)
    p = D.panel({"start": _snap(-1000, 0, 5000)})
    f = dict((r[0], r) for r in p["groups"]["Fields (uniform estimate)"])
    assert f["extraction field, liquid"][1] == "4.22"
