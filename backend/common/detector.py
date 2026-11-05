"""The detector panel of the run page: slow-control values at the start and end of a run (run document field
sc_snapshot, written by webinterface/scripts/sc_snapshot.py since run 7579), the voltage differences and the fields.

Only sc_snapshot: never voltages from run comments (user, 2026-11-05).

Fields: uniform estimates from the geometry (xams-sim config/detectors/xams2026/geometry.yaml):
    drift field       (V_gate - V_cathode) / gate-cathode distance
    extraction field  in the liquid: (V_anode - V_gate) / (d_LXe + eps_ratio * d_GXe), in the gas eps_ratio times that
"""
from __future__ import annotations

GATE_CATHODE_CM = 5.18
GATE_ANODE_CM = 0.8
LEVEL_ABOVE_GATE_CM = 0.4          # 4 mm LXe + 4 mm GXe since SR-2026.2 (user, 2026-10-01)
EPS_RATIO = 1.96                   # eps(LXe) / eps(GXe)

ELECTRODES = [("cathode", "cathode"), ("gate", "gate"), ("anode", "anode"), ("ts", "top screen"),
              ("bs", "bottom screen"), ("pmt_top", "PMT top"), ("pmt_bot", "PMT bottom"), ("sipm_eq", "SiPM equalizer")]
OTHER = [("pmain", "pressure"), ("tt401", "temperature TT401"), ("tt402", "temperature TT402"), ("fm101", "flow FM101")]


def _v(snap, key):
    """(value, unit, flag) of one slow-control value of a snapshot, or (None, '', '')."""
    e = ((snap or {}).get("values") or {}).get(key) or {}
    q = e.get("quality")
    return e.get("value"), e.get("unit") or "", ("" if q in (None, "ok") else str(q))


def _fmt(v, digits=4):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:.{digits}g}" if abs(v) < 1e5 else f"{v:.3e}"
    return str(v)


def _fields(snap):
    vc, vg, va = (_v(snap, f"hv_{k}_vmon")[0] for k in ("cathode", "gate", "anode"))
    out = {}
    if vc is not None and vg is not None:
        out["ΔV gate − cathode"] = (vg - vc, "V")
        out["drift field"] = ((vg - vc) / GATE_CATHODE_CM, "V/cm")
    if va is not None and vg is not None:
        d_l, d_g = LEVEL_ABOVE_GATE_CM, GATE_ANODE_CM - LEVEL_ABOVE_GATE_CM
        e_l = (va - vg) / (d_l + EPS_RATIO * d_g)
        out["ΔV anode − gate"] = (va - vg, "V")
        out["extraction field, liquid"] = (e_l / 1e3, "kV/cm")
        out["extraction field, gas"] = (EPS_RATIO * e_l / 1e3, "kV/cm")
    return out


def panel(sc: dict | None) -> dict:
    """What the template shows: rows [(label, start, end, unit, note)] per group; times; a message if there is no
    snapshot."""
    sc = sc or {}
    start, end = sc.get("start"), sc.get("end")
    if not start and not end:
        return {"message": "no slow-control snapshot in the run document (written since run 7579)"}
    msg = []
    for which, s in (("start", start), ("end", end)):
        if s and "unavailable" in s:
            msg.append(f"{which}: slow control unavailable ({s['unavailable']})")
        elif not s:
            msg.append(f"{which}: no snapshot")
    groups = {"High voltage": [], "Fields (uniform estimate)": [], "Detector": []}
    for key, label in ELECTRODES:
        (v1, u, f1), (v2, _, f2) = _v(start, f"hv_{key}_vmon"), _v(end, f"hv_{key}_vmon")
        (i1, iu, _), (i2, _, _) = _v(start, f"hv_{key}_imon"), _v(end, f"hv_{key}_imon")
        if v1 is None and v2 is None:
            continue
        cur = f"{_fmt(i1, 3)} / {_fmt(i2, 3)} {iu}" if (i1 is not None or i2 is not None) else ""
        groups["High voltage"].append((label, _fmt(v1), _fmt(v2), u or "V", " ".join(x for x in (cur, f1, f2) if x)))
    f_s, f_e = _fields(start), _fields(end)
    for k in dict.fromkeys(list(f_s) + list(f_e)):
        a, b = f_s.get(k, (None, "")), f_e.get(k, (None, ""))
        unit = a[1] or b[1]
        n = 4 if unit == "V" else 3                      # volts to the volt, fields to three digits
        groups["Fields (uniform estimate)"].append((k, _fmt(a[0], n), _fmt(b[0], n), unit, ""))
    for key, label in OTHER:
        (v1, u, f1), (v2, _, f2) = _v(start, key), _v(end, key)
        if v1 is None and v2 is None:
            continue
        groups["Detector"].append((label, _fmt(v1), _fmt(v2), u, " ".join(x for x in (f1, f2) if x)))
    times = {w: str((s or {}).get("time") or "")[:19] for w, s in (("start", start), ("end", end))}
    return {"groups": {k: v for k, v in groups.items() if v}, "times": times, "config": (start or end or {}).get("sc_config"),
            "message": "; ".join(msg),
            "geometry": f"gate–cathode {GATE_CATHODE_CM * 10:g} mm, gate–anode {GATE_ANODE_CM * 10:g} mm, "
                        f"liquid {LEVEL_ABOVE_GATE_CM * 10:g} mm above the gate, ε(LXe)/ε(GXe) {EPS_RATIO}"}
