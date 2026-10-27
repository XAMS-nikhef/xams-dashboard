"""The data view: runs and data sets of a profile's folders, status (current / outdated / unknown / incomplete) from
its providers, "why?", plots of any stored version, keep marks and deletion. One code base for the private dashboard
(v2/private_app.py, profile "private") and the production page /v3 (v2/app.py, profile "production"); the profiles
(backend/common/profile.py) hold what differs.

    blueprint(profile)   Flask blueprint with the page and its API; register it at the profile's URL prefix
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from backend.common import folder as F
from backend.common import stored
from backend.common import whatchanged as W
from backend.common.lineage import Lineage, provider_name
from backend.common.profile import MC_RUNS, NEVER_TYPES, RAW_TYPES

RUNDOC_TTL = 600
SCAN_TTL = 60                     # seconds a folder scan is reused before a new one starts (in the background)
PLOT_FIELDS = {
    "event": ["s1_area", "s2_area", "cs1", "cs2", "drift_time", "x", "y", "s1_area_fraction_top"],
    "peak": ["area", "area_fraction_top", "range_50p_area", "type"],
}


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


class DataView:
    def __init__(self, profile):
        self.p = profile
        self.lineage = Lineage(profile.state_dir, profile.providers)
        self._rundocs: dict = {}
        self._stored_lineage: dict = {}
        self._scan = (0.0, [])
        self._scan_lock = threading.Lock()
        self._scanning = False

    # -------------------------------------------------------------------------------------------- folders
    def _scan_now(self):
        ds = []
        for i, loc in enumerate(self.p.locations):
            try:
                ds += F.scan(loc.path, loc=i, min_run=self.p.min_run)
            except OSError:
                continue
        self._scan = (time.time(), ds)
        return ds

    def _scan_bg(self):
        try:
            self._scan_now()
        finally:
            self._scanning = False

    def datasets_raw(self) -> list:
        """The data sets of all locations: the last scan, renewed in the background when older than SCAN_TTL. The
        first scan also runs in the background (large folders take minutes); until it is done: waited for up to 5 s,
        then an empty list (the page says "scanning")."""
        t, ds = self._scan
        if not t:
            with self._scan_lock:
                if not self._scanning and not self._scan[0]:
                    self._scanning = True
                    threading.Thread(target=self._scan_bg, daemon=True).start()
            for _ in range(50):
                if self._scan[0]:
                    return self._scan[1]
                time.sleep(0.1)
            return []
        if time.time() - t > SCAN_TTL and not self._scanning:
            self._scanning = True
            threading.Thread(target=self._scan_bg, daemon=True).start()
        return ds

    def location(self, d):
        return self.p.locations[d.loc]

    def find(self, ds_id: str):
        loc, name = F.split_id(ds_id)
        if not (0 <= loc < len(self.p.locations)):
            raise ValueError("unknown location")
        F._target(self.p.locations[loc].path, name)              # name pattern, inside the folder, a real folder
        d = next((x for x in self.datasets_raw() if x.loc == loc and x.name == name), None)
        if d is None:                                            # newer than the last scan
            d = next((x for x in F.scan(self.p.locations[loc].path, loc=loc) if x.name == name), None)
        if d is None:
            raise ValueError("no such data set")
        return d

    # -------------------------------------------------------------------------------------------- run information
    def rundocs(self, runs) -> dict:
        """Short run information from the run database (read-only), cached; data runs from runs_gas, simulated
        runs from runs_mc."""
        now = time.time()
        need = [r for r in runs if r not in self._rundocs or now - self._rundocs[r][0] > RUNDOC_TTL]
        if need:
            try:
                import amstrax  # type: ignore
                found = {}
                proj = {"number": 1, "mode": 1, "start": 1, "end": 1, "xams_bookkeeping": 1, "tags": 1, "comments": 1,
                        "_id": 0}
                for mc, part in ((False, [r for r in need if r < MC_RUNS[0]]), (True, [r for r in need if r >= MC_RUNS[0]])):
                    if not part:
                        continue
                    coll = amstrax.get_mongo_collection("xams_mc" if mc else "xams")
                    for d in coll.find({"number": {"$in": part}}, proj):
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
                    self._rundocs[r] = (now, found.get(r, {}))
            except Exception as e:                               # noqa: BLE001 (no database: folder view only)
                for r in need:
                    self._rundocs[r] = (now, {"error": str(e)[:200]})
        return {r: self._rundocs[r][1] for r in runs}

    # -------------------------------------------------------------------------------------------- status
    def why(self, d) -> dict | None:
        cur = self.lineage.current_lineages(d)
        if not cur:
            return None
        key = (d.loc, d.name)
        hit = self._stored_lineage.get(key)
        if not hit or hit[0] != d.mtime:
            try:
                hit = (d.mtime, W.stored_lineage(self.location(d).path, d.name))
            except Exception as e:                               # noqa: BLE001
                hit = (d.mtime, {"_error": str(e)[:200]})
            self._stored_lineage[key] = hit
        out = []
        for name, lin in cur:
            dd = W.diff(hit[1], lin, d.dtype)
            out.append({"provider": name, **dd, "labels": W.labels(dd)})
        return {"providers": out, "labels": sorted({lab for x in out for lab in x["labels"]})}

    def protected(self, d) -> str | None:
        """Why this data set can never be deleted by the data view (None: it can, under the profile's rules)."""
        if d.dtype in NEVER_TYPES:
            return "live data are never deleted"
        return None

    def rows(self, kind: str | None = None) -> list:
        ds = self.datasets_raw()
        self.lineage.start(ds)                                   # compute what is missing (background, no-op if done)
        keep = F.load_keep(self.p.state_dir)
        out = []
        for d in ds:
            if kind in ("data", "mc") and (MC_RUNS[0] <= d.run <= MC_RUNS[1]) != (kind == "mc"):
                continue
            row = F.as_dict(d)
            row.update(self.lineage.status(d), keep=d.id in keep, keep_note=(keep.get(d.id) or {}).get("note", ""),
                       location=self.location(d).label, raw=self.location(d).raw or d.dtype in RAW_TYPES)
            if row["status"] == "outdated":
                w = self.why(d)
                row["why_labels"], row["why_pending"] = (w["labels"], False) if w else ([], True)
            out.append(row)
        return out

    # -------------------------------------------------------------------------------------------- deletion
    def delete(self, ids: list, confirm: bool = False) -> dict:
        """Preview (confirm False) or delete data sets under the profile's rules; every deletion logged."""
        status = {r["id"]: r for r in self.rows()}
        keep = F.load_keep(self.p.state_dir)
        ok, refused = [], []
        for ds_id in dict.fromkeys(ids):
            try:
                d = self.find(ds_id)
            except ValueError as e:
                refused.append({"name": ds_id, "reason": str(e)})
                continue
            row = status.get(d.id) or {"status": self.lineage.status(d)["status"]}
            reason = self.protected(d)
            raw = self.location(d).raw or d.dtype in RAW_TYPES
            if reason is None and d.id in keep:
                reason = "marked keep"
            if reason is None and self.p.delete_statuses is not None and row["status"] not in self.p.delete_statuses:
                reason = f"{self.p.name}: only {' / '.join(sorted(self.p.delete_statuses))} data sets ({row['status']})"
            if reason is None and raw and self.p.raw_rule:
                reason = self.p.raw_rule(d)
            if reason:
                refused.append({"name": d.id, "reason": reason})
                continue
            item = {"name": d.id, "size": d.size, "n_files": d.n_files}
            if raw:
                item["note"] = "raw records: rebuilt from the live data when needed (takes longer)"
            ok.append((d, item))
        out = {"confirm": bool(confirm), "delete": [x for _, x in ok], "refused": refused,
               "size": sum(x["size"] for _, x in ok), "deleted": [], "errors": []}
        if not confirm:
            return out
        self.p.state_dir.mkdir(parents=True, exist_ok=True)
        log = self.p.state_dir / F.LOG_FILE
        for d, item in ok:
            loc = self.location(d)
            try:
                shutil.rmtree(F._target(loc.path, d.name))
                note = self.p.on_delete(d, loc) if self.p.on_delete else ""
                out["deleted"].append(d.id)
                with open(log, "a") as f:
                    f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "user": getpass.getuser(),
                                        "name": d.id, "location": str(loc.path), "size": d.size,
                                        "status": (status.get(d.id) or {}).get("status"), "note": note}) + "\n")
            except Exception as e:                               # noqa: BLE001
                out["errors"].append({"name": d.id, "error": str(e)})
        self._scan = (time.time() - SCAN_TTL - 1, self._scan[1])  # rescan in the background at the next request
        return out


def _totals(rows) -> dict:
    by = {}
    for r in rows:
        k = "keep" if r["keep"] else r["status"]
        by[k] = by.get(k, 0) + r["size"]
    return {"size": sum(r["size"] for r in rows), "n_datasets": len(rows), "n_runs": len({r["run"] for r in rows}),
            "size_by_status": by}


# ------------------------------------------------------------------------------------------------ blueprint
def blueprint(profile, base: str = "") -> Blueprint:
    """The page and its API for one profile; `base` is the URL prefix it is registered at ("" or "/v3")."""
    view = DataView(profile)
    bp = Blueprint("dataview", __name__, template_folder="templates", static_folder="static/dataview",
                   static_url_path="/static/dataview")
    bp.view = view

    @bp.get("/")
    def index():
        return render_template("dataview/index.html", base=base, profile=profile, user=os.getenv("USER", ""),
                               locations=[str(x.path) for x in profile.locations],
                               providers=[provider_name(p, i) for i, p in enumerate(profile.providers)])

    @bp.get("/api/runs")
    def runs():
        """?kind=data (runs below 900000) or mc (simulated runs 900000-999999); totals for that kind."""
        rows = view.rows(request.args.get("kind"))
        by_run: dict = {}
        for r in rows:
            by_run.setdefault(r["run"], []).append(r)
        info = view.rundocs(sorted(by_run))
        out = []
        for run in sorted(by_run, reverse=True):
            ds = by_run[run]
            out.append({"run": run, "info": info.get(run, {}), "size": sum(d["size"] for d in ds),
                        "outdated_size": sum(d["size"] for d in ds if d["status"] in ("outdated", "incomplete")
                                             and not d["keep"]),
                        "datasets": ds})
        return jsonify({"runs": out, "totals": _totals(rows), "lineage": view.lineage.state,
                        "scanning": not view._scan[0],
                        "delete_statuses": sorted(profile.delete_statuses) if profile.delete_statuses else None})

    @bp.get("/api/run/<int:run>")
    def run_detail(run: int):
        rows = [r for r in view.rows() if r["run"] == run]
        if not rows:
            return jsonify({"error": "no data sets of this run in the folders"}), 404
        return jsonify({"run": run, "info": view.rundocs([run]).get(run, {}), "datasets": rows,
                        "provider_errors": {k: v.get(f"{run:06d}") for k, v in view.lineage.errors().items()
                                            if v.get(f"{run:06d}")}})

    @bp.get("/api/dataset/<ds_id>/why")
    def dataset_why(ds_id: str):
        try:
            d = view.find(ds_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        st = view.lineage.status(d)
        if st["status"] != "outdated":
            return jsonify({"name": ds_id, "status": st["status"], "why": None})
        w = view.why(d)
        return jsonify({"name": ds_id, "status": "outdated", "pending": w is None, "why": w})

    @bp.get("/api/dataset/<ds_id>/meta")
    def dataset_meta(ds_id: str):
        try:
            d = view.find(ds_id)
            return jsonify(stored.metadata(view.location(d).path, d.name))
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"error": str(e)}), 400

    @bp.get("/api/dataset/<ds_id>/plot")
    def dataset_plot(ds_id: str):
        """Columns for the plots of one data set (events: S1 / S2, drift time, x-y; peaks: area, top fraction, width)."""
        try:
            d = view.find(ds_id)
            kind = "peak" if d.dtype.startswith("peak") else "event"
            n = min(200000, max(1000, int(request.args.get("max_rows", 60000))))
            a = stored.read(view.location(d).path, d.name, max_rows=n, fields=PLOT_FIELDS[kind])
            cols = {}
            for f in a.dtype.names:
                v = a[f].astype(float)
                cols[f] = [None if not (x == x) or abs(x) == float("inf") else float(x) for x in v]
            return jsonify({"name": ds_id, "kind": kind, "n": len(a), "columns": cols})
        except Exception as e:                                   # noqa: BLE001
            return jsonify({"error": str(e)}), 400

    @bp.post("/api/refresh")
    def refresh():
        view.lineage.start(view.datasets_raw(), refresh=True)
        return jsonify(view.lineage.state)

    @bp.post("/api/keep")
    def keep():
        b = request.get_json(force=True, silent=True) or {}
        try:
            profile.state_dir.mkdir(parents=True, exist_ok=True)
            F.set_keep(profile.state_dir, str(b.get("name", "")), bool(b.get("keep")), str(b.get("note") or "")[:200])
        except (ValueError, OSError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @bp.post("/api/delete")
    def delete():
        """{"names": [ids], "confirm": false} -> preview; with confirm true: delete under the profile's rules."""
        b = request.get_json(force=True, silent=True) or {}
        return jsonify(view.delete([str(x) for x in (b.get("names") or [])][:5000], confirm=bool(b.get("confirm"))))

    @bp.post("/api/delete-outdated")
    def delete_outdated():
        """All outdated (with "incomplete": true also unfinished) data sets that are not kept, optionally older than
        N days, of one kind (data / mc); preview unless confirm."""
        b = request.get_json(force=True, silent=True) or {}
        statuses = {"outdated"} | ({"incomplete"} if b.get("incomplete") else set())
        cutoff = time.time() - float(b.get("older_than_days") or 0) * 86400
        ids = [r["id"] for r in view.rows(b.get("kind"))
               if r["status"] in statuses and not r["keep"] and r["mtime"] <= cutoff]
        return jsonify(view.delete(ids, confirm=bool(b.get("confirm"))))

    @bp.get("/api/deletions")
    def deletions():
        return jsonify({"rows": F.deletion_log(profile.state_dir)})

    return bp
