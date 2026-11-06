"""The setup page (gear icon) of the private dashboard: the user's folders, checked before they are saved.

    Central data   /data/xenon/xams_v2/xams_processed, xams_raw_records      shown, not changeable
    Central MC     /data/xenon/xams_v2/mc_processed, mc_raw_records          shown, not changeable
    Private data   strax_folder                                              required, writable (state files)
    Private MC     mc_processed_folder, mc_raw_folder                        optional

Saved into the private settings file (~/.xams/private.json, mode 600; every other key is kept), then the server
restarts itself with the new folders.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from backend.common.profile import XAMS, private_location_problem

DATASET = re.compile(r"^(\d{6})-[A-Za-z0-9_]+-[a-z0-9]{10}$")

# (key, group, label, required)
FIELDS = [
    ("strax_folder", "Private data", "your strax folder (processed data)", True),
    ("mc_processed_folder", "Private MC", "reconstruction of your MC (amstrax output)", False),
    ("mc_raw_folder", "Private MC", "raw records + run documents of your MC (xams-sim)", False),
]
CENTRAL = [
    ("Central data", XAMS / "xams_processed"), ("Central data", XAMS / "xams_raw_records"),
    ("Central MC", XAMS / "mc_processed"), ("Central MC", XAMS / "mc_raw_records"),
]
MAX_SCAN = 200_000                       # entries counted at most (a very large folder: "at least")


def check_folder(path: str, need_write: bool = False) -> dict:
    """Does the folder exist, can this account read (and write) it, how many runs and data sets does it hold, and is it
    read-only for a private dashboard (central, live data, someone else's)?"""
    out = {"path": path, "ok": False, "exists": False, "readable": False, "writable": False,
           "n_runs": 0, "n_datasets": 0, "read_only": None, "message": ""}
    if not path:
        out["message"] = "empty"
        return out
    p = Path(path)
    if not p.is_absolute():
        out["message"] = "give the full path (starting with /)"
        return out
    if not p.is_dir():
        out["message"] = "no such folder" if not p.exists() else "not a folder"
        return out
    out["exists"] = True
    out["readable"] = os.access(p, os.R_OK | os.X_OK)
    out["writable"] = os.access(p, os.W_OK | os.X_OK)
    if not out["readable"]:
        out["message"] = "not readable for you"
        return out
    runs, n, partial = set(), 0, False
    try:
        with os.scandir(p) as it:
            for i, e in enumerate(it):
                if i >= MAX_SCAN:
                    partial = True
                    break
                m = DATASET.match(e.name)
                if m:
                    n += 1
                    runs.add(m.group(1))
    except OSError as e:
        out["message"] = f"cannot list it ({e.strerror})"
        return out
    out.update(n_runs=len(runs), n_datasets=n, partial=partial)
    out["read_only"] = private_location_problem(p)
    if need_write and not out["writable"]:
        out["message"] = "not writable for you (the dashboard keeps its state files here)"
        return out
    out["ok"] = True
    more = "at least " if partial else ""
    out["message"] = (f"{more}{len(runs)} runs, {more}{n} data sets" if n else "readable, no data sets yet")
    if out["read_only"]:
        out["message"] += f"; shown read-only: {out['read_only']}"
    return out


class Setup:
    """The folders of the private settings file: read, check, save (then restart the server)."""

    def __init__(self, settings_path: Path, restart=None):
        self.path = Path(settings_path)
        self.restart = restart if restart is not None else restart_self

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    def state(self) -> dict:
        d = self._read()
        from backend.common import users
        u = users.for_account()
        return {
            "editable": True,
            "settings_file": str(self.path),
            "central": [{"group": g, "path": str(p), "exists": p.is_dir()} for g, p in CENTRAL],
            "fields": [{"key": k, "group": g, "label": lab, "required": req, "value": str(d.get(k) or "")}
                       for k, g, lab, req in FIELDS],
            "user": ({"name": u.name, "account": u.account, "dashboard_port": u.dashboard_port,
                      "sim_port": u.sim_port, "central_actions": u.central_actions} if u else None),
        }

    def check(self, key: str, value: str) -> dict:
        req = {k: r for k, _, _, r in FIELDS}
        if key not in req:
            raise ValueError(f"unknown field {key!r}")
        if not value and not req[key]:
            return {"path": "", "ok": True, "message": "not used"}
        return check_folder(value, need_write=(key == "strax_folder"))

    def save(self, values: dict) -> dict:
        """Check every field; save only when all are fine; then restart (the response goes out first)."""
        checks = {k: self.check(k, str(values.get(k) or "").strip()) for k, *_ in FIELDS}
        bad = {k: c["message"] for k, c in checks.items() if not c["ok"]}
        if bad:
            return {"saved": False, "checks": checks, "errors": bad}
        d = self._read()
        changed = False
        for k, *_ in FIELDS:
            v = str(values.get(k) or "").strip()
            if (d.get(k) or "") != v:
                changed = True
            if v:
                d[k] = v
            else:
                d.pop(k, None)
        if not changed:
            return {"saved": False, "unchanged": True, "checks": checks}
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=1)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        self.restart()
        return {"saved": True, "checks": checks, "restarting": True}


def restart_self(delay: float = 1.0):
    """Start this server again (same command, same environment) after `delay` s, so the answer still goes out."""
    def go():
        time.sleep(delay)
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, "-m", "v2.private_app"])
    threading.Thread(target=go, daemon=True).start()
