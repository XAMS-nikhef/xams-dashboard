"""What changed: why a data set is outdated (docs/PRIVATE_MODE_PLAN.md, 3.3).

A strax lineage is {data_type: [plugin, version, {option: value}]} for the data type and everything it is made from.
The stored data set's lineage (its metadata) is compared with the lineage the provider that makes it would use now:
per data type in the chain, plugin version changes and option changes (old -> new), and data types that are new or
gone. A data set is outdated through its own plugin ("own") and/or through earlier data types ("through").

Every change also gets a short label, the same for all data sets with that change, for the summary over the folder
("PeakPositions 1.2.26 → 2.1.0: 312 data sets").
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def norm(v):
    """JSON-normalised value: lists and tuples, numpy scalars, ... compare as equal when their JSON is equal."""
    return json.loads(json.dumps(v, default=str, sort_keys=True))


def short(v, n: int = 60) -> str:
    """A readable short form of an option value (file names from resource URLs, long values cut)."""
    if v is None:
        return "—"
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    m = re.search(r"filename=([^&]+)", s)
    if m:
        s = m.group(1)
    elif s.startswith(("/", "file://")) and "/" in s:
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s if len(s) <= n else s[: n - 1] + "…"


def diff(old: dict, new: dict, dtype: str) -> dict:
    """Changes between a stored lineage (old) and the current one (new) of data type dtype."""
    old, new = norm(old or {}), norm(new or {})
    changes = []
    for k in sorted(set(old) | set(new)):
        o, n = old.get(k), new.get(k)
        if o == n:
            continue
        if o is None:
            changes.append({"dtype": k, "kind": "new", "plugin": n[0], "version": [None, n[1]], "options": {}})
            continue
        if n is None:
            changes.append({"dtype": k, "kind": "gone", "plugin": o[0], "version": [o[1], None], "options": {}})
            continue
        oo, no = o[2] if len(o) > 2 else {}, n[2] if len(n) > 2 else {}
        opts = {c: [oo.get(c), no.get(c)] for c in sorted(set(oo) | set(no)) if oo.get(c) != no.get(c)}
        changes.append({"dtype": k, "kind": "changed", "plugin": n[0] if o[0] == n[0] else f"{o[0]} → {n[0]}",
                        "version": [o[1], n[1]] if o[1] != n[1] else None, "options": opts})
    return {"own": any(c["dtype"] == dtype for c in changes),
            "through": [c["dtype"] for c in changes if c["dtype"] != dtype], "changes": changes}


def labels(d: dict) -> list:
    """One short label per change (the same for every data set with that change)."""
    out = []
    for c in d.get("changes", []):
        if c["kind"] == "new":
            out.append(f"new in the chain: {c['dtype']} ({c['plugin']} {c['version'][1]})")
        elif c["kind"] == "gone":
            out.append(f"no longer in the chain: {c['dtype']} ({c['plugin']})")
        else:
            if c["version"]:
                out.append(f"{c['plugin']} {c['version'][0]} → {c['version'][1]}")
            for opt, (a, b) in c["options"].items():
                out.append(f"{c['plugin']}: {opt} {short(a, 40)} → {short(b, 40)}")
    return out


def stored_lineage(folder: Path, name: str) -> dict:
    """The lineage in a data set's metadata (folder <run>-<type>-<hash>, file <type>-<hash>-metadata.json)."""
    run, rest = name.split("-", 1)
    path = Path(folder) / name / f"{rest}-metadata.json"
    if path.exists():
        return json.loads(path.read_text()).get("lineage") or {}
    import strax                                             # older layouts
    return strax.FileSytemBackend().get_metadata(str(Path(folder) / name)).get("lineage") or {}
