"""Run information of a simulated run (xams-sim, runs 900000-999999) for the run page.

The run document is written by xams-sim (xamssim.amstrax_io.write): for production MC also into run.runs_mc, for
private MC only as the file <run>-metadata.json in the store next to the raw records. Its block `xamssim` holds what
was simulated; since xams-sim #59 also `xamssim.summary` (state, voltages, field estimates, source, physics), grouped
for display. Older documents without it get the groups that can be read from the rest of the block.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

GROUPS = ("state", "voltages [V]", "source", "physics")


def _hook(d):
    """bson extended JSON as strax / xams-sim write it: {"$date": ...} -> datetime."""
    if len(d) == 1 and "$date" in d:
        v = d["$date"]
        try:
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(v / 1e3, tz=timezone.utc)
            if isinstance(v, dict) and "$numberLong" in v:
                return datetime.fromtimestamp(int(v["$numberLong"]) / 1e3, tz=timezone.utc)
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return v
    return d


def read_file(folders, run: int) -> dict | None:
    """The run document <run6>-metadata.json from the first of these folders that holds it, or None."""
    for f in folders:
        p = Path(f) / f"{run:06d}-metadata.json"
        try:
            return json.loads(p.read_text(), object_hook=_hook)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            continue
    return None


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k} {_fmt(x)}" for k, x in v.items())
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    return str(v)


def _flat(d: dict, prefix: str = "") -> dict:
    """{'nest.widths.A_ER': 0.067, ...}: nested physics settings as one table."""
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def facts(doc: dict) -> list:
    """(label, value) rows of the Run panel."""
    x = doc.get("xamssim") or {}
    com = doc.get("comments") or []
    rows = [("mode", doc.get("mode")), ("class", "simulation (xams-sim)"), ("run name", x.get("run_name")),
            ("state", x.get("state")), ("source", x.get("source")), ("detector", x.get("detector")),
            ("decays", f"{x['n_events']:.3g}" if isinstance(x.get("n_events"), (int, float)) else x.get("n_events")),
            ("seed", x.get("seed")), ("made", x.get("made")), ("supersedes", x.get("supersedes")),
            ("tags", ", ".join(str(t) for t in doc.get("tags") or [])),
            ("run file", x.get("run_file")), ("run key", x.get("run_key")), ("condition", x.get("condition")),
            ("comment", com[-1].get("comment") if com and isinstance(com[-1], dict) else None)]
    return [(k, _fmt(v)) for k, v in rows if v not in (None, "", [])]


def groups(doc: dict) -> dict:
    """{group: {label: value}} panels: xamssim.summary when there, else what the rest of the block gives."""
    x = doc.get("xamssim") or {}
    s = x.get("summary") or {}
    out = {}
    if s:
        for g in GROUPS:
            items = _flat(s.get(g) or {}) if g == "physics" else (s.get(g) or {})
            if items:
                out[g] = {k: _fmt(v) for k, v in items.items() if v is not None}
    else:
        st = {"state": x.get("state"), "detector": x.get("detector")}
        out["state"] = {k: _fmt(v) for k, v in st.items() if v}
        src = {"source": x.get("source"), "position [mm]": x.get("source_position_mm")}
        out["source"] = {k: _fmt(v) for k, v in src.items() if v}
    truth = ((x.get("corrections") or {}).get("truth")) or x.get("truth") or {}
    tr = {}
    if truth.get("electron_drift_velocity"):
        tr["drift velocity [mm/µs]"] = truth["electron_drift_velocity"] * 1e4      # cm/ns -> mm/µs
    for k, lab in (("drift_time_gate", "drift time gate [µs]"), ("drift_time_cathode", "drift time cathode [µs]")):
        if truth.get(k) is not None:
            tr[lab] = truth[k] / 1e3
    if truth.get("elife"):
        tr["electron lifetime [µs]"] = truth["elife"] / 1e3
    cal = (x.get("corrections") or {}).get("calibrated") or {}
    if cal:
        tr["calibrated"] = f"version {cal.get('version')} from run {cal.get('from_run')}"
    if tr:
        out["true corrections"] = {k: _fmt(v) for k, v in tr.items()}
    if x.get("maps"):
        out["maps"] = {k: str(v) for k, v in x["maps"].items()}
    return {g: items for g, items in out.items() if items}


def note(doc: dict) -> str:
    """The subtitle of the panels: where the values come from."""
    s = ((doc.get("xamssim") or {}).get("summary")) or {}
    if not s:
        return "simulated (run document without a summary: made before xams-sim #59)"
    return "simulated" + (f" (summary added {s['backfilled']})" if s.get("backfilled") else "")
