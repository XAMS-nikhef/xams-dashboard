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


def test_groups_like_simulations():
    g = D.groups({"start": _snap(-1546.2, -1046.0, 2501.0)})
    assert list(g) == ["state", "voltages [V]"]
    assert g["voltages [V]"] == {"A": "2501", "G": "-1046", "C": "-1546"}
    assert g["state"]["drift field [V/cm]"] == "96.6" and g["state"]["pressure [bar]"] == "1.85"
    assert g["state"]["liquid level above gate [mm]"] == "4"
    assert D.groups({}) == {}


def test_gap_per_period():
    """Up to run 8109 (SR-2026.3) the anode hung ring side down: 9.30 mm gate-anode, 4 mm LXe + 5.30 mm GXe."""
    assert D.gap(8109) == (0.930, "xams_sr2026_3") and D.gap(7790) == (0.930, "xams_sr2026_3")
    assert D.gap(8110)[0] == 0.80 and D.gap(None)[0] == 0.80
    p = D.panel({"start": _snap(-1546.2, -1046.0, 2501.0)}, run=8103)
    assert dict((k, v) for k, v, _ in p["tiles"])["extraction (liquid)"] == "2.47"    # 3547 V / (0.4 + 1.96 * 0.53) cm
    r = {k: v for k, v, _, _ in p["rows"]}
    assert r["extraction field, gas"] == "4.83" and "9.3 mm (xams_sr2026_3)" in p["geometry"]
    g = D.groups({"start": _snap(-1546.2, -1046.0, 2501.0)}, run=8103)
    assert g["state"]["gate − anode gap [mm]"] == "9.3" and g["state"]["extraction field, liquid [kV/cm]"] == "2.47"
