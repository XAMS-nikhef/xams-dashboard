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
    """What the run page shows (user, 2026-11-05): the conditions at the start of the run only, as one row of tiles
    (fields, electrode voltages, pressure) plus the other start values in a table. The end snapshot is used only when
    there is no start snapshot (and then said so)."""
    sc = sc or {}
    snap, which = sc.get("start"), "start"
    if not snap or "unavailable" in snap:
        if sc.get("end") and "unavailable" not in sc["end"]:
            snap, which = sc["end"], "end"
    if not snap or "unavailable" in snap:
        why = (snap or {}).get("unavailable")
        return {"message": f"slow control unavailable at the start ({why})" if why else
                "no slow-control snapshot in the run document (written since run 7579)"}
    f = _fields(snap)
    tiles = []
    for label, (v, u), n in (("drift field", f.get("drift field", (None, "V/cm")), 3),
                             ("extraction (liquid)", f.get("extraction field, liquid", (None, "kV/cm")), 3)):
        tiles.append((label, _fmt(v, n), u))
    for key, label in ELECTRODES[:3]:
        v, u, _ = _v(snap, f"hv_{key}_vmon")
        tiles.append((label, _fmt(v), u or "V"))
    v, u, _ = _v(snap, "pmain")
    tiles.append(("pressure", _fmt(v), u))
    rows = []
    for k in ("ΔV gate − cathode", "ΔV anode − gate", "extraction field, gas"):
        if k in f:
            rows.append((k, _fmt(f[k][0], 4 if f[k][1] == "V" else 3), f[k][1], ""))
    for key, label in ELECTRODES[3:]:
        v, u, q = _v(snap, f"hv_{key}_vmon")
        i, iu, _ = _v(snap, f"hv_{key}_imon")
        if v is not None:
            rows.append((label, _fmt(v), u or "V", " ".join(x for x in (f"{_fmt(i, 3)} {iu}" if i is not None else "", q) if x)))
    for key, label in ELECTRODES[:3]:
        i, iu, q = _v(snap, f"hv_{key}_imon")
        if i is not None:
            rows.append((f"{label} current", _fmt(i, 3), iu, q))
    for key, label in OTHER[1:]:
        v, u, q = _v(snap, key)
        if v is not None:
            rows.append((label, _fmt(v), u, q))
    return {"tiles": tiles, "rows": rows, "which": which, "time": str(snap.get("time") or "")[:19],
            "config": snap.get("sc_config"), "message": "" if which == "start" else "no start snapshot: values at the end",
            "geometry": f"gate–cathode {GATE_CATHODE_CM * 10:g} mm, gate–anode {GATE_ANODE_CM * 10:g} mm, "
                        f"liquid {LEVEL_ABOVE_GATE_CM * 10:g} mm above the gate, ε(LXe)/ε(GXe) {EPS_RATIO}"}
