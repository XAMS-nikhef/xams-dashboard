"""Waiting list for submissions refused because the job limit was reached.

auto_processing.py refuses to submit when too many runs are 'submitted'/'running'
in the run DB. Instead of dropping those requests, the dashboard keeps them in a
small JSON file and a background thread retries them, oldest first, until the
limit leaves room again.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class SubmitQueue:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.last_attempt: Optional[str] = None
        self.last_message: str = ""

    # -- storage -----------------------------------------------------------
    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                items = json.load(f)
            return items if isinstance(items, list) else []
        except Exception:
            return []

    def _save(self, items: List[Dict[str, Any]]) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1, default=str)
        os.replace(tmp, self.path)

    # -- public API --------------------------------------------------------
    def items(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def queued_run_ids(self) -> set:
        return {int(x["run_id"]) for x in self.items()}

    def add(self, request: Dict[str, Any]) -> bool:
        """Add a submit request; returns False if the run is already waiting."""
        with self._lock:
            items = self._load()
            if any(int(x["run_id"]) == int(request["run_id"]) for x in items):
                return False
            entry = dict(request)
            entry["queued_at"] = datetime.utcnow().isoformat(timespec="seconds")
            entry["attempts"] = 0
            items.append(entry)
            self._save(items)
            return True

    def remove(self, run_id: Optional[int] = None) -> int:
        """Remove one run (or all when run_id is None); returns number removed."""
        with self._lock:
            items = self._load()
            keep = [] if run_id is None else [x for x in items if int(x["run_id"]) != int(run_id)]
            self._save(keep)
            return len(items) - len(keep)

    def status(self) -> Dict[str, Any]:
        return {
            "items": self.items(),
            "last_attempt": self.last_attempt,
            "last_message": self.last_message,
            "worker_alive": bool(self._thread and self._thread.is_alive()),
        }

    # -- worker ------------------------------------------------------------
    def process_once(self, submit: Callable[[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Try the waiting runs in order; stop at the first one refused as busy.

        `submit(request)` must return a result dict with a 'status' key
        (submitted / busy / failed / skipped / ...). Runs that are not busy leave
        the list whatever the outcome; the result is recorded by `submit`.
        """
        results = []
        with self._lock:
            items = self._load()
        self.last_attempt = datetime.utcnow().isoformat(timespec="seconds")
        if not items:
            self.last_message = "waiting list empty"
            return results
        for entry in items:
            result = submit(entry)
            results.append(result)
            with self._lock:
                current = self._load()
                if result.get("status") == "busy":
                    for x in current:
                        if int(x["run_id"]) == int(entry["run_id"]):
                            x["attempts"] = int(x.get("attempts", 0)) + 1
                            x["last_reason"] = result.get("reason", "")
                    self._save(current)
                    self.last_message = "run {}: {}".format(entry["run_id"], result.get("reason", "busy"))
                    break
                self._save([x for x in current if int(x["run_id"]) != int(entry["run_id"])])
                self.last_message = "run {}: {}".format(entry["run_id"], result.get("status"))
        return results

    def start(self, submit: Callable[[Dict[str, Any]], Dict[str, Any]], interval_s: int = 120) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _loop():
            while not self._stop.wait(interval_s):
                try:
                    self.process_once(submit)
                except Exception as e:  # keep the worker alive
                    self.last_message = "worker error: {}".format(e)

        self._thread = threading.Thread(target=_loop, name="submit-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
