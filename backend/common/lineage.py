"""Which data sets are current: the lineage hashes the user's context providers would make now, compared with the
hashes in the folder names.

Status of a data set:
    current     its hash is the one a provider makes now (names of the matching providers)
    outdated    a provider makes this data type for this run, with another hash (old gains, old settings)
    unknown     no provider makes it (run or data type unknown to all of them)
    incomplete  a "_temp" folder (strax did not finish)
    pending     not computed yet

The hashes are computed in the background, one subprocess per provider (lineage_worker.py), and cached in the strax
folder (.dashboard_lineage.json) per provider fingerprint; after them, for every outdated data set, the full current
lineage of the providers that make it (for "what changed", whatchanged.py). Fingerprint: the provider's settings plus the modification times of its
file and its "watch" paths (e.g. the analysis config folder with gains and processing settings) and, for an amstrax
provider with a corrections_version, the content of that version in amstrax_files (the _global file and the files it
names): lineages hold file names, not contents, so a version that moves under the same name (ONLINE) must still make the
provider compute again. A change there makes the provider compute again; "refresh" forces it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
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


_FP: dict = {}                                # provider (json) -> (time, fingerprint)
FP_TTL = 10.0                                 # seconds a fingerprint is reused (it stats the watched files)


def fingerprint(provider: dict) -> str:
    key = json.dumps(provider, sort_keys=True, default=str)
    hit = _FP.get(key)
    if hit and time.time() - hit[0] < FP_TTL:
        return hit[1]
    fp = _fingerprint(provider)
    _FP[key] = (time.time(), fp)
    return fp


def _fingerprint(provider: dict) -> str:
    watch = list(provider.get("watch") or [])
    if provider.get("path"):
        watch.append(provider["path"])
    blob = {"provider": provider, "mtimes": _mtimes(watch)}
    version = (provider.get("kwargs") or {}).get("corrections_version") if provider.get("kind") == "amstrax" else None
    if version:
        blob["corrections"] = corrections_signature(str(version))
    return hashlib.sha1(json.dumps(blob, sort_keys=True).encode()).hexdigest()[:12]


# Content of a corrections version in amstrax_files, as amstrax fetches it (raw GitHub, master). The lineage of a data set
# holds the correction *file names*; ONLINE keeps its names while their content changes, so the name alone does not tell
# whether the cached hashes are still right.
CORRECTIONS_URL = os.environ.get("XAMS_DASH_CORRECTIONS_URL",
                                 "https://raw.githubusercontent.com/XAMS-nikhef/amstrax_files/master/corrections")
SIG_TTL = 600.0                               # seconds a version's signature is reused (one fetch per file per 10 min)
_SIG: dict = {}                               # version -> (time, signature)


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()


def corrections_signature(version: str):
    """sha1 of the _global file of a corrections version and of every .json file it names (dir = name up to the last
    '_', as amstrax's get_correction). On a fetch error the last known signature is kept (None if never fetched), so a
    network hiccup does not make every provider compute again."""
    hit = _SIG.get(version)
    if hit and time.time() - hit[0] < SIG_TTL:
        return hit[1]
    try:
        g = _fetch(f"{CORRECTIONS_URL}/_global/_global_{version}.json")
        h = hashlib.sha1(g)
        for name in sorted(v for v in json.loads(g).values() if isinstance(v, str) and v.endswith(".json")):
            h.update(name.encode() + _fetch(f"{CORRECTIONS_URL}/{name.rsplit('_', 1)[0]}/{name}"))
        sig = h.hexdigest()[:12]
    except Exception:                         # noqa: BLE001  (offline, GitHub down, unknown version)
        sig = hit[1] if hit else None
    _SIG[version] = (time.time(), sig)
    return sig


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
        self.version = 0                      # changes whenever the cache changes (for caches built on it)
        self.cache = self._load()

    # cache: {fingerprint: {"name": ..., "hashes": {run6: {dtype: hash|null}}, "errors": {run6: msg},
    #                       "lineages": {run6: {dtype: lineage}}}}   (lineages: only of outdated data sets)
    def _load(self) -> dict:
        try:
            return json.loads((self.folder / CACHE_FILE).read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self):
        self.version += 1
        self.folder.mkdir(parents=True, exist_ok=True)
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

    def _lineage_todo(self, datasets) -> list:
        """[(provider index, fingerprint, {run6: [dtypes]})]: current lineages still missing for outdated data sets
        (of every provider that makes the data type for the run)."""
        out = {}
        for d in datasets:
            if self.status(d)["status"] != "outdated":
                continue
            run = f"{d.run:06d}"
            for i, p in enumerate(self.providers):
                fp = fingerprint(p)
                entry = self.cache.get(fp) or {}
                if (entry.get("hashes", {}).get(run) or {}).get(d.dtype) is None:
                    continue
                if d.dtype in (entry.get("lineages", {}).get(run) or {}):
                    continue
                out.setdefault((i, fp), {}).setdefault(run, set()).add(d.dtype)
        return [(i, fp, {r: sorted(t) for r, t in m.items()}) for (i, fp), m in out.items()]

    def start(self, datasets, refresh: bool = False):
        """Compute what is missing (all again with refresh), in a background thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if refresh:
                fps = {fingerprint(p) for p in self.providers}
                self.cache = {k: v for k, v in self.cache.items() if k not in fps}
                self.version += 1
            todo = self._todo(datasets)
            if not todo and not self._lineage_todo(datasets):
                return
            self.state.update(running=True, error="")
            self._thread = threading.Thread(target=self._run, args=(todo, list(datasets)), daemon=True)
            self._thread.start()

    def _run(self, todo, datasets=()):
        try:
            self._hashes(todo)
            self._lineages(self._lineage_todo(datasets))
            self.state["done_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:                               # noqa: BLE001
            self.state["error"] = str(e)[:500]
        finally:
            self.state["running"] = False

    def _lineages(self, todo):
        for i, fp, miss in todo:
            p = self.providers[i]
            entry = self.cache.setdefault(fp, {"name": provider_name(p, i), "hashes": {}, "errors": {}})
            items = sorted(miss.items())
            for k in range(0, len(items), BATCH):
                res = run_worker(p, items[k:k + BATCH], want="lineage")
                if res.get("fatal"):
                    raise RuntimeError(f"{provider_name(p, i)}: {res['fatal']}")
                for r, h in res.get("hashes", {}).items():
                    entry.setdefault("lineages", {}).setdefault(r, {}).update({t: v for t, v in h.items() if v})
                with self._lock:
                    self._save()

    def current_lineages(self, d) -> list:
        """[(provider name, current lineage)] of the providers that make data set d's type for its run."""
        run, out = f"{d.run:06d}", []
        for i, p in enumerate(self.providers):
            lin = ((self.cache.get(fingerprint(p)) or {}).get("lineages", {}).get(run) or {}).get(d.dtype)
            if lin:
                out.append((provider_name(p, i), lin))
        return out

    def _hashes(self, todo):
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


def run_worker(provider: dict, items: list, timeout: int = 3600, want: str = "hash") -> dict:
    """One worker call: lineage hashes (want "lineage": full lineages) of `items` [(run6, [dtypes])] for one provider,
    in its own python."""
    py = provider.get("python") or sys.executable
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)                              # the provider's python, not the dashboard's paths
    r = subprocess.run([py, str(WORKER)], input=json.dumps({"provider": provider, "items": items, "want": want}),
                       capture_output=True, text=True, timeout=timeout, env=env)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if r.returncode != 0 or not lines:
        return {"fatal": f"worker failed (exit {r.returncode}): {r.stderr[-400:]}"}
    return json.loads(lines[-1])
