"""Which data sets are current: the lineage hashes the user's context providers would make now, compared with the
hashes in the folder names.

Status of a data set:
    current     its hash is the one a provider makes now (names of the matching providers)
    outdated    a provider makes this data type for this run, with another hash (old gains, old settings)
    unknown     no provider makes it (run or data type unknown to all of them)
    incomplete  a "_temp" folder (strax did not finish)
    pending     not computed yet

The hashes are computed in the background, one subprocess per provider (lineage_worker.py), and cached in the strax
folder (.dashboard_lineage.json) per provider fingerprint: the provider's settings plus the modification times of its
file and its "watch" paths (e.g. the analysis config folder with gains and processing settings). A change there makes
the provider compute again; "refresh" forces it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

CACHE_FILE = ".dashboard_lineage.json"
WORKER = Path(__file__).with_name("lineage_worker.py")
BATCH = 40                                    # runs per worker call (results are saved after each batch)


def _mtimes(paths) -> list:
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += [(str(f), f.stat().st_mtime) for f in sorted(p.iterdir()) if f.is_file()]
        elif p.exists():
            out.append((str(p), p.stat().st_mtime))
    return out


def fingerprint(provider: dict) -> str:
    watch = list(provider.get("watch") or [])
    if provider.get("path"):
        watch.append(provider["path"])
    blob = json.dumps({"provider": provider, "mtimes": _mtimes(watch)}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def provider_name(provider: dict, i: int) -> str:
    return str(provider.get("name") or f"context {i + 1}")


class Lineage:
    """Background computation and cache of the providers' hashes for the data sets of one folder."""

    def __init__(self, folder: Path, providers: list):
        self.folder = Path(folder)
        self.providers = list(providers)
        self._lock = threading.Lock()
        self._thread = None
        self.state = {"running": False, "error": "", "done_at": None}
        self.cache = self._load()

    # cache: {fingerprint: {"name": ..., "hashes": {run6: {dtype: hash|null}}, "errors": {run6: msg}}}
    def _load(self) -> dict:
        try:
            return json.loads((self.folder / CACHE_FILE).read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self):
        f = self.folder / CACHE_FILE
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache))
        tmp.replace(f)

    def _todo(self, datasets) -> list:
        """[(provider index, fingerprint, {run6: [dtypes]})] still to compute."""
        wanted: dict = {}
        for d in datasets:
            wanted.setdefault(f"{d.run:06d}", set()).add(d.dtype)
        out = []
        for i, p in enumerate(self.providers):
            fp = fingerprint(p)
            known = (self.cache.get(fp) or {}).get("hashes", {})
            miss = {r: sorted(t - set(known.get(r, {}))) for r, t in wanted.items()}
            miss = {r: t for r, t in miss.items() if t}
            if miss:
                out.append((i, fp, miss))
        return out

    def start(self, datasets, refresh: bool = False):
        """Compute what is missing (all again with refresh), in a background thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if refresh:
                fps = {fingerprint(p) for p in self.providers}
                self.cache = {k: v for k, v in self.cache.items() if k not in fps}
            todo = self._todo(datasets)
            if not todo:
                return
            self.state.update(running=True, error="")
            self._thread = threading.Thread(target=self._run, args=(todo,), daemon=True)
            self._thread.start()

    def _run(self, todo):
        try:
            for i, fp, miss in todo:
                p = self.providers[i]
                entry = self.cache.setdefault(fp, {"name": provider_name(p, i), "hashes": {}, "errors": {}})
                items = sorted(miss.items())
                for k in range(0, len(items), BATCH):
                    res = run_worker(p, items[k:k + BATCH])
                    if res.get("fatal"):
                        raise RuntimeError(f"{provider_name(p, i)}: {res['fatal']}")
                    for r, h in res.get("hashes", {}).items():
                        entry["hashes"].setdefault(r, {}).update(h)
                    entry["errors"].update(res.get("errors", {}))
                    with self._lock:
                        self._save()
            self.state["done_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:                               # noqa: BLE001
            self.state["error"] = str(e)[:500]
        finally:
            self.state["running"] = False

    def status(self, d) -> dict:
        """Status of one data set (module doc) and the providers that make it now."""
        if d.temp:
            return {"status": "incomplete", "current_for": []}
        run, pending, current, made = f"{d.run:06d}", False, [], False
        for i, p in enumerate(self.providers):
            entry = self.cache.get(fingerprint(p))
            h = ((entry or {}).get("hashes", {}).get(run) or {})
            if d.dtype not in h:
                pending = True
                continue
            if h[d.dtype] is None:
                continue
            made = True
            if h[d.dtype] == d.hash:
                current.append(provider_name(p, i))
        if current:
            return {"status": "current", "current_for": current}
        if made:
            return {"status": "outdated", "current_for": []}
        return {"status": "pending" if pending else "unknown", "current_for": []}

    def errors(self) -> dict:
        """Per provider: runs it could not make a context for (e.g. not in its run table)."""
        out = {}
        for i, p in enumerate(self.providers):
            out[provider_name(p, i)] = (self.cache.get(fingerprint(p)) or {}).get("errors", {})
        return out


def run_worker(provider: dict, items: list, timeout: int = 3600) -> dict:
    """One worker call: lineage hashes of `items` [(run6, [dtypes])] for one provider, in its own python."""
    py = provider.get("python") or sys.executable
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)                              # the provider's python, not the dashboard's paths
    r = subprocess.run([py, str(WORKER)], input=json.dumps({"provider": provider, "items": items}),
                       capture_output=True, text=True, timeout=timeout, env=env)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if r.returncode != 0 or not lines:
        return {"fatal": f"worker failed (exit {r.returncode}): {r.stderr[-400:]}"}
    return json.loads(lines[-1])
