"""Process for the private dashboard: make data types of runs with the user's own analysis contexts, as condor jobs
under the user's own account (docs/PRIVATE_MODE_PLAN.md, Process button).

- provider: the one that makes the run's data types now (the same that marks them current), unless chosen;
- targets: given, or "@outdated" = the run's outdated data types;
- one job per run (batch name xamsdash_<run>), running backend/common/make_worker.py in the provider's python;
  job files and logs in <state folder>/.dashboard_jobs/<run>/;
- at most `max_jobs` (settings) of these jobs in condor at once; the rest waits on a waiting list
  (<state folder>/.dashboard_queue.json) that a background thread submits from when there is room.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from backend.common.lineage import provider_name

WORKER = Path(__file__).resolve().parents[1] / "common" / "make_worker.py"
BATCH = "xamsdash_"
OUTDATED = "@outdated"
CONDOR_STATES = {1: "idle", 2: "running", 3: "removed", 4: "completed", 5: "held", 6: "transferring", 7: "suspended"}


class PrivateProcessing:
    def __init__(self, view, max_jobs: int = 10, memory_mb: int = 8000, interval_s: int = 60):
        self.view = view                                  # the DataView (rows, lineage, profile)
        self.max_jobs = max_jobs
        self.memory_mb = memory_mb
        self.jobs_dir = Path(view.p.state_dir) / ".dashboard_jobs"
        self.queue_file = Path(view.p.state_dir) / ".dashboard_queue.json"
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, args=(interval_s,), daemon=True)
        self._thread.start()

    # -------------------------------------------------------------------------------------------- condor
    def condor_jobs(self) -> dict:
        """{run: state} of this user's dashboard jobs in condor."""
        try:
            out = subprocess.run(["condor_q", os.environ.get("USER", ""), "-af", "JobBatchName", "JobStatus"],
                                 capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return {}
        jobs = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].startswith(BATCH) and parts[0][len(BATCH):].isdigit():
                jobs[int(parts[0][len(BATCH):])] = CONDOR_STATES.get(int(parts[1]), parts[1])
        return jobs

    def jobs(self) -> dict:
        out = self.condor_jobs()
        for q in self._queue():
            out.setdefault(int(q["run"]), "queued")
        return out

    # -------------------------------------------------------------------------------------------- waiting list
    def _queue(self) -> list:
        try:
            return json.loads(self.queue_file.read_text())
        except (FileNotFoundError, ValueError):
            return []

    def _save_queue(self, q):
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(q, indent=1))
        tmp.replace(self.queue_file)

    def _loop(self, interval_s):
        while True:
            time.sleep(interval_s)
            try:
                self.process_queue()
            except Exception:                                    # noqa: BLE001 (next round)
                pass

    def process_queue(self) -> list:
        """Submit from the waiting list while there is room; returns what was submitted."""
        with self._lock:
            q = self._queue()
            if not q:
                return []
            room = self.max_jobs - len(self.condor_jobs())
            done, rest = [], []
            for item in q:
                if room > 0:
                    res = self._submit_one(item)
                    done.append(res)
                    if res["status"] == "submitted":
                        room -= 1
                else:
                    rest.append(item)
            self._save_queue(rest)
            return done

    # -------------------------------------------------------------------------------------------- submission
    def provider_for(self, run: int, name: str | None = None):
        """The provider (index, spec) for a run: the named one, else the first that makes data types of the run."""
        provs = self.view.p.providers
        if name and name != "auto":
            for i, p in enumerate(provs):
                if provider_name(p, i) == name:
                    return i, p
            raise ValueError(f"no analysis context '{name}'")
        run6 = f"{run:06d}"
        from backend.common.lineage import fingerprint
        for i, p in enumerate(provs):
            hashes = ((self.view.lineage.cache.get(fingerprint(p)) or {}).get("hashes", {}).get(run6) or {})
            if any(v for v in hashes.values()):
                return i, p
        raise ValueError("no analysis context knows this run (status 'unknown'): add it to the analysis' run table")

    def targets_for(self, run: int, targets: list) -> list:
        if OUTDATED not in targets:
            return [t for t in targets if t]
        rows = [r for r in self.view.rows() if r["run"] == run]
        current = {r["dtype"] for r in rows if r["status"] == "current"}
        out = sorted({r["dtype"] for r in rows if r["status"] == "outdated" and not r["raw"]} - current)
        return out + [t for t in targets if t and t != OUTDATED and t not in out]

    def submit(self, run_ids, targets, version) -> dict:
        """The private dashboard's Process: one job per run, under the job limit, the rest on the waiting list."""
        results = []
        with self._lock:
            room = self.max_jobs - len(self.condor_jobs())
            queued = {int(q["run"]) for q in self._queue()}
            q = self._queue()
            for run in run_ids:
                try:
                    _, prov = self.provider_for(int(run), version)
                    tg = self.targets_for(int(run), targets or [OUTDATED])
                except ValueError as e:
                    results.append({"run_id": run, "status": "failed", "reason": str(e)})
                    continue
                if not tg:
                    results.append({"run_id": run, "status": "skipped", "reason": "nothing to make (no outdated data types)"})
                    continue
                item = {"run": int(run), "provider": prov, "targets": tg}
                if int(run) in queued:
                    results.append({"run_id": run, "status": "queued", "reason": "already on the waiting list"})
                elif room > 0:
                    res = self._submit_one(item)
                    results.append(res)
                    room -= res["status"] == "submitted"
                else:
                    q.append(item)
                    results.append({"run_id": run, "status": "queued",
                                    "reason": f"{self.max_jobs} jobs running: on the waiting list ({', '.join(tg)})"})
            self._save_queue(q)
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"submitted": counts.get("submitted", 0), "queued": counts.get("queued", 0),
                "skipped": counts.get("skipped", 0), "failed": counts.get("failed", 0), "results": results}

    def _submit_one(self, item) -> dict:
        run, prov, tg = int(item["run"]), item["provider"], item["targets"]
        d = self.jobs_dir / f"{run:06d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "request.json").write_text(json.dumps({"provider": prov, "run": f"{run:06d}", "targets": tg}, indent=1))
        py = prov.get("python") or sys.executable
        (d / "job.sh").write_text(f"#!/bin/bash\n# private dashboard job: run {run:06d}, {', '.join(tg)}\n"
                                  f"cd {d}\nexec {py} {WORKER} {d / 'request.json'}\n")
        (d / "job.sh").chmod(0o755)
        (d / "job.sub").write_text(
            f"executable     = {d / 'job.sh'}\nbatch_name     = {BATCH}{run:06d}\n"
            f"log            = {d / 'job.log'}\noutput         = {d / 'job.out'}\nerror          = {d / 'job.err'}\n"
            f"request_memory = {self.memory_mb}MB\nrequest_cpus   = 1\ngetenv         = True\n"
            f'+UseOS         = "el9"\n+JobCategory   = "medium"\nqueue\n')
        try:
            r = subprocess.run(["condor_submit", str(d / "job.sub")], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"run_id": run, "status": "failed", "reason": f"condor_submit: {e}"}
        if r.returncode != 0:
            return {"run_id": run, "status": "failed", "reason": (r.stderr or r.stdout)[-300:]}
        return {"run_id": run, "status": "submitted", "reason": f"{', '.join(tg)} with {prov.get('name')} (logs {d})"}

    def options(self) -> dict:
        names = [provider_name(p, i) for i, p in enumerate(self.view.p.providers)]
        return {"targets": [OUTDATED, "peak_basics", "peak_positions", "event_basics", "event_positions", "event_info",
                            "corrected_areas", "peaks_sipm"],
                "default_targets": [OUTDATED],
                "target_labels": {OUTDATED: "the run's outdated data types"},
                "corrections_versions": ["auto"] + names, "default_version": "auto",
                "version_label": "analysis context", "version_labels": {"auto": "auto: the one that knows the run"},
                "submit_mode": "on (your own condor jobs)", "max_jobs": self.max_jobs}
