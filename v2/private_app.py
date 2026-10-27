"""Private dashboard: the processed data in the user's own strax folder (docs/PRIVATE_MODE_PLAN.md).

Run as the user, from their own checkout:  ops/start_private.sh   (settings ~/.xams/private.json)
Separate from the production dashboard (v2/app.py): own process, port and templates; it reads the run database only,
and deletes only data-set folders inside the user's strax folder. Every request needs the token of the settings
(?token=... once, then a cookie), so other users on the same host cannot use it.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import time
from datetime import datetime

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request

from backend.private import folder as F
from backend.private import stored
from backend.private import whatchanged as W
from backend.private.lineage import Lineage, provider_name
from backend.private.settings import PrivateSettings

S = PrivateSettings.load()
app = Flask(__name__, template_folder="templates", static_folder="static")
lineage = Lineage(S.strax_folder, S.contexts)
COOKIE = "xams_private_token"
MC_RUNS = (900000, 999999)              # simulated runs (xams-sim): the MC tab; everything else: the Data tab
_RUNDOCS: dict = {}                     # run -> (time, summary of its run document)
_STORED_LINEAGE: dict = {}              # data set name -> (mtime, lineage from its metadata)
RUNDOC_TTL = 600


# ------------------------------------------------------------------------------------------------ access
class _HideToken(logging.Filter):
    """The request log must not show the token (the log file may be readable by others)."""
    def filter(self, record):
        record.msg = re.sub(r"token=[^\s&\"]+", "token=***", str(record.msg))
        if record.args:
            record.args = tuple(re.sub(r"token=[^\s&\"]+", "token=***", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


logging.getLogger("werkzeug").addFilter(_HideToken())


def _token_ok(value) -> bool:
    return bool(S.token) and bool(value) and hmac.compare_digest(str(value), S.token)


@app.before_request
def _check_token():
    if not S.token:
        abort(make_response("no token in the private settings: start the app with ops/start_private.sh", 403))
    if not (_token_ok(request.args.get("token")) or _token_ok(request.cookies.get(COOKIE))
            or _token_ok(request.headers.get("X-Token"))):
        abort(make_response("forbidden: open the private dashboard with its token (launcher, or the link printed by "
                            "ops/start_private.sh)", 403))


@app.after_request
def _set_cookie(resp):
    if _token_ok(request.args.get("token")):
        resp.set_cookie(COOKIE, S.token, httponly=True, samesite="Strict", max_age=30 * 24 * 3600)
    resp.headers["Cache-Control"] = "no-cache"               # after an update the browser fetches the new page / JS
    return resp


@app.before_request
def _drop_token_from_url():
    """A page opened with ?token=: the cookie is set, then the same page without the token in its address."""
    if request.method == "GET" and request.path == "/" and request.args.get("token"):
        return redirect("/", code=302)


# ------------------------------------------------------------------------------------------------ helpers
def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _rundocs(runs) -> dict:
    """Short run information from the run database (read-only), cached."""
    now = time.time()
    need = [r for r in runs if r not in _RUNDOCS or now - _RUNDOCS[r][0] > RUNDOC_TTL]
    if need:
        try:
            import amstrax  # type: ignore
            coll = amstrax.get_mongo_collection()
            found = {}
            for d in coll.find({"number": {"$in": need}}, {"number": 1, "mode": 1, "start": 1, "end": 1,
                                                           "xams_bookkeeping": 1, "tags": 1, "comments": 1, "_id": 0}):
                xb = d.get("xams_bookkeeping") or {}
                com = d.get("comments") or []
                last = com[-1].get("comment", "") if com and isinstance(com[-1], dict) else ""
                found[d["number"]] = {
                    "mode": d.get("mode") or "", "start": _iso(d.get("start")), "end": _iso(d.get("end")),
                    "source": xb.get("source_type") or "", "run_class": xb.get("run_class") or "",
                    "science_run": xb.get("science_run_id") or "",
                    "tags": [t.get("name") if isinstance(t, dict) else str(t) for t in d.get("tags") or []],
                    "comment": str(last)[:200]}
            for r in need:
                _RUNDOCS[r] = (now, found.get(r, {}))
        except Exception as e:                               # noqa: BLE001 (no database: folder view only)
            for r in need:
                _RUNDOCS[r] = (now, {"error": str(e)[:200]})
    return {r: _RUNDOCS[r][1] for r in runs}


def _why(d) -> dict | None:
    """What changed for an outdated data set: per provider that makes it, the diff of its stored lineage with the
    current one (None while the current lineage is not computed yet)."""
    cur = lineage.current_lineages(d)
    if not cur:
        return None
    hit = _STORED_LINEAGE.get(d.name)
    if not hit or hit[0] != d.mtime:
        try:
            hit = (d.mtime, W.stored_lineage(S.strax_folder, d.name))
        except Exception as e:                               # noqa: BLE001
            hit = (d.mtime, {"_error": str(e)[:200]})
        _STORED_LINEAGE[d.name] = hit
    out = []
    for name, lin in cur:
        dd = W.diff(hit[1], lin, d.dtype)
        out.append({"provider": name, **dd, "labels": W.labels(dd)})
    return {"providers": out, "labels": sorted({lab for x in out for lab in x["labels"]})}


def _kind_ok(run: int, kind: str | None) -> bool:
    if kind not in ("data", "mc"):
        return True
    return (MC_RUNS[0] <= run <= MC_RUNS[1]) == (kind == "mc")


def _datasets(kind: str | None = None):
    ds = F.scan(S.strax_folder)
    lineage.start(ds)                                        # compute what is missing (background, no-op if done)
    keep = F.load_keep(S.strax_folder)
    rows = []
    for d in ds:
        row = F.as_dict(d)
        row.update(lineage.status(d), keep=d.name in keep, keep_note=(keep.get(d.name) or {}).get("note", ""))
        if row["status"] == "outdated":
            w = _why(d)
            row["why_labels"], row["why_pending"] = (w["labels"], False) if w else ([], True)
        rows.append(row)
    return [r for r in rows if _kind_ok(r["run"], kind)]


def _why_summary(rows) -> list:
    """Over all outdated data sets that are not kept: per change, how many data sets (per data type) and how much."""
    out: dict = {}
    for r in rows:
        if r["status"] != "outdated" or r["keep"]:
            continue
        for lab in r.get("why_labels") or ["(not computed yet)" if r.get("why_pending") else "(no difference found)"]:
            e = out.setdefault(lab, {"label": lab, "n": 0, "size": 0, "by_dtype": {}, "runs": set()})
            e["n"] += 1
            e["size"] += r["size"]
            e["by_dtype"][r["dtype"]] = e["by_dtype"].get(r["dtype"], 0) + 1
            e["runs"].add(r["run"])
    res = sorted(out.values(), key=lambda e: -e["size"])
    for e in res:
        e["n_runs"] = len(e.pop("runs"))
    return res


def _totals(rows) -> dict:
    by = {}
    for r in rows:
        k = "keep" if r["keep"] else r["status"]
        by[k] = by.get(k, 0) + r["size"]
    return {"size": sum(r["size"] for r in rows), "n_datasets": len(rows), "n_runs": len({r["run"] for r in rows}),
            "size_by_status": by}


# ------------------------------------------------------------------------------------------------ pages, API
@app.get("/")
def index():
    return render_template("private/index.html", folder=str(S.strax_folder), user=os.getenv("USER", ""),
                           providers=[provider_name(p, i) for i, p in enumerate(S.contexts)])


@app.get("/api/overview")
def overview():
    rows = _datasets()
    return jsonify({"folder": str(S.strax_folder), "totals": _totals(rows), "lineage": lineage.state,
                    "providers": [provider_name(p, i) for i, p in enumerate(S.contexts)],
                    "provider_errors": {k: len(v) for k, v in lineage.errors().items()}})


@app.get("/api/runs")
def runs():
    """?kind=data (runs below 900000) or mc (simulated runs 900000-999999); totals and summary for that kind."""
    rows = _datasets(request.args.get("kind"))
    by_run: dict = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)
    info = _rundocs(sorted(by_run))
    out = []
    for run in sorted(by_run, reverse=True):
        ds = by_run[run]
        out.append({"run": run, "info": info.get(run, {}), "size": sum(d["size"] for d in ds),
                    "outdated_size": sum(d["size"] for d in ds if d["status"] in ("outdated", "incomplete")
                                         and not d["keep"]),
                    "datasets": ds})
    return jsonify({"runs": out, "totals": _totals(rows), "lineage": lineage.state, "why_summary": _why_summary(rows)})


@app.get("/api/run/<int:run>")
def run_detail(run: int):
    rows = [r for r in _datasets() if r["run"] == run]
    if not rows:
        return jsonify({"error": "no data sets of this run in the folder"}), 404
    return jsonify({"run": run, "info": _rundocs([run]).get(run, {}), "datasets": rows,
                    "provider_errors": {k: v.get(f"{run:06d}") for k, v in lineage.errors().items()
                                        if v.get(f"{run:06d}")}})


@app.get("/api/dataset/<name>/why")
def dataset_why(name: str):
    """What changed for one data set (outdated): per provider the changes, old -> new."""
    try:
        F._target(S.strax_folder, name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    d = next((x for x in F.scan(S.strax_folder) if x.name == name), None)
    st = lineage.status(d)
    if st["status"] != "outdated":
        return jsonify({"name": name, "status": st["status"], "why": None})
    w = _why(d)
    return jsonify({"name": name, "status": "outdated", "pending": w is None, "why": w})


@app.get("/api/dataset/<name>/meta")
def dataset_meta(name: str):
    try:
        F._target(S.strax_folder, name)
        return jsonify(stored.metadata(S.strax_folder, name))
    except Exception as e:                                   # noqa: BLE001
        return jsonify({"error": str(e)}), 400


PLOT_FIELDS = {
    "event": ["s1_area", "s2_area", "cs1", "cs2", "drift_time", "x", "y", "s1_area_fraction_top"],
    "peak": ["area", "area_fraction_top", "range_50p_area", "type"],
}


@app.get("/api/dataset/<name>/plot")
def dataset_plot(name: str):
    """Columns for the plots of one data set (events: S1 / S2, drift time, x-y; peaks: area, top fraction, width)."""
    try:
        F._target(S.strax_folder, name)
        p = F.parse(name)
        kind = "peak" if p["dtype"].startswith("peak") else "event"
        n = min(200000, max(1000, int(request.args.get("max_rows", 60000))))
        a = stored.read(S.strax_folder, name, max_rows=n, fields=PLOT_FIELDS[kind])
        cols = {}
        for f in a.dtype.names:
            v = a[f].astype(float)
            cols[f] = [None if not (x == x) or abs(x) == float("inf") else float(x) for x in v]
        return jsonify({"name": name, "kind": kind, "n": len(a), "columns": cols})
    except Exception as e:                                   # noqa: BLE001
        return jsonify({"error": str(e)}), 400


@app.post("/api/refresh")
def refresh():
    lineage.start(F.scan(S.strax_folder), refresh=True)
    return jsonify(lineage.state)


@app.post("/api/keep")
def keep():
    b = request.get_json(force=True, silent=True) or {}
    try:
        F.set_keep(S.strax_folder, str(b.get("name", "")), bool(b.get("keep")), str(b.get("note") or "")[:200])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.post("/api/delete")
def delete():
    """{"names": [...], "confirm": false} -> preview; with confirm true: delete (not kept ones, only in the folder)."""
    b = request.get_json(force=True, silent=True) or {}
    names = [str(x) for x in (b.get("names") or [])][:5000]
    return jsonify(F.delete(S.strax_folder, names, confirm=bool(b.get("confirm"))))


@app.post("/api/delete-outdated")
def delete_outdated():
    """All outdated (and with "incomplete": true also unfinished) data sets that are not kept, optionally only those
    older than N days, of one kind ("kind": data / mc, as the tab shown); preview unless confirm."""
    b = request.get_json(force=True, silent=True) or {}
    days = float(b.get("older_than_days") or 0)
    statuses = {"outdated"} | ({"incomplete"} if b.get("incomplete") else set())
    cutoff = time.time() - days * 86400
    names = [r["name"] for r in _datasets(b.get("kind"))
             if r["status"] in statuses and not r["keep"] and r["mtime"] <= cutoff]
    return jsonify(F.delete(S.strax_folder, names, confirm=bool(b.get("confirm"))))


@app.get("/api/deletions")
def deletions():
    return jsonify({"rows": F.deletion_log(S.strax_folder)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=S.dashboard_port, debug=False)
