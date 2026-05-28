from __future__ import annotations

import subprocess
import getpass
from typing import Any, Optional
from datetime import datetime

from pymongo import MongoClient

from .config import settings
from .models import DataEntry, RunDetails, RunSummary


class MongoService:
    def __init__(self, mongo_uri: str  = None):
        self.client = None
        self.runs = None
        self._init_collections(mongo_uri)
        self.processing = self.client[settings.processing_db][settings.processing_collection]
        self.settings = self.client[settings.processing_db]["settings"]

    def _init_collections(self, mongo_uri: str = None) -> None:
        # Prefer amstrax tunnel-aware access on STBC.
        try:
            import amstrax  # type: ignore

            self.client = amstrax.get_mongo_client()
            self.runs = amstrax.get_mongo_collection()
            return
        except Exception:
            pass

        self.client = MongoClient(mongo_uri or settings.mongo_uri)
        self.runs = self.client[settings.run_db][settings.run_collection]

    @staticmethod
    def _processing_status_value(ps: Any) -> str:
        if isinstance(ps, dict):
            return ps.get("status", "unknown")
        if isinstance(ps, str):
            return ps
        return "unknown"

    @staticmethod
    def _normalize_data_entry(entry: dict[str, Any]) -> DataEntry:
        return DataEntry(
            data_type=entry.get("type", "unknown"),
            host=entry.get("host"),
            location=entry.get("location"),
            lineage_hash=entry.get("lineage_hash") or entry.get("lineage") or entry.get("hash"),
            amstrax_version=entry.get("amstrax_version"),
            raw=entry,
        )

    @staticmethod
    def _bookkeeping(doc: dict[str, Any]) -> dict[str, Any]:
        xbk = doc.get("xams_bookkeeping", {})
        return xbk if isinstance(xbk, dict) else {}

    @staticmethod
    def _normalize_sr(value: str) -> str:
        v = str(value or "").strip()
        if not v:
            return ""
        if v.upper().startswith("SR-"):
            return "SR-" + v[3:]
        if v and v[0].isdigit():
            return f"SR-{v}"
        return v

    def get_active_science_run(self) -> str:
        doc = self.settings.find_one({"name": "active_science_run"})
        if doc and doc.get("value"):
            return self._normalize_sr(doc.get("value"))
        legacy = self.processing.find_one({"name": "active_science_run"})
        if legacy and legacy.get("value"):
            return self._normalize_sr(legacy.get("value"))
        return ""

    def list_science_runs(self) -> list[str]:
        vals = self.runs.distinct("xams_bookkeeping.science_run_id")
        out = [str(v).strip() for v in vals if v]
        out = [v for v in out if v]
        out.sort(reverse=True)
        return out

    def get_runs(self, page: int = 1, page_size: int = 25, status: str  = None) -> list[RunSummary]:
        page = max(1, page)
        query: dict[str, Any] = {}
        if status:
            query["processing_status.status"] = status

        cursor = self.runs.find(
            query,
            {
                "number": 1,
                "mode": 1,
                "start": 1,
                "end": 1,
                "processing_status": 1,
                "data.type": 1,
                "xams_bookkeeping.science_run_id": 1,
                "xams_bookkeeping.run_class": 1,
                "xams_bookkeeping.source_type": 1,
                "_id": 0,
            },
        ).sort("number", -1)

        if page_size is not None and page_size > 0:
            cursor = cursor.skip((page - 1) * page_size).limit(page_size)

        out: list[RunSummary] = []
        for doc in cursor:
            ps = doc.get("processing_status")
            dtypes = [d.get("type") for d in doc.get("data", []) if isinstance(d, dict)]
            xbk = self._bookkeeping(doc)
            out.append(
                RunSummary(
                    number=int(doc["number"]),
                    mode=doc.get("mode"),
                    start=doc.get("start"),
                    end=doc.get("end"),
                    processing_status=self._processing_status_value(ps),
                    has_raw_records=("raw_records" in dtypes),
                    has_events=("events" in dtypes or "event_info" in dtypes),
                    has_led_calibration=("led_calibration" in dtypes),
                    science_run_id=xbk.get("science_run_id") or "",
                    run_class=xbk.get("run_class") or "",
                    source_type=xbk.get("source_type") or "",
                )
            )
        return out

    def get_runs_page(
        self,
        page: int = 1,
        page_size: int = 25,
        status: str = None,
        query_text: str = None,
        science_run_id: str = None,
        run_mode: str = None,
        run_class: str = None,
        source_type: str = None,
        default_active_sr: bool = True,
    ) -> tuple[list[RunSummary], int]:
        page = max(1, page)
        page_size = max(1, page_size)
        query: dict[str, Any] = {}

        if status:
            query["processing_status.status"] = status
        if run_class:
            query["xams_bookkeeping.run_class"] = run_class
        if source_type:
            query["xams_bookkeeping.source_type"] = source_type
        if run_mode:
            query["mode"] = run_mode
        active_filter_applied = False
        if science_run_id:
            query["xams_bookkeeping.science_run_id"] = science_run_id
        elif default_active_sr:
            active_sr = self.get_active_science_run()
            if active_sr:
                query["xams_bookkeeping.science_run_id"] = active_sr
                active_filter_applied = True

        q = (query_text or "").strip()
        if q:
            ors: list[dict[str, Any]] = [
                {"mode": {"$regex": q, "$options": "i"}},
                {"processing_status.status": {"$regex": q, "$options": "i"}},
                {"xams_bookkeeping.science_run_id": {"$regex": q, "$options": "i"}},
                {"xams_bookkeeping.source_type": {"$regex": q, "$options": "i"}},
            ]
            if q.isdigit():
                ors.insert(0, {"number": int(q)})
            query["$or"] = ors

        total = self.runs.count_documents(query)
        # Backward-compat fallback: if active SR is set but legacy runs have no SR bookkeeping yet,
        # show runs instead of an empty table.
        if (
            total == 0
            and active_filter_applied
            and not science_run_id
            and not run_class
            and not source_type
            and not run_mode
            and not status
            and not q
        ):
            query.pop("xams_bookkeeping.science_run_id", None)
            total = self.runs.count_documents(query)
        cursor = (
            self.runs.find(
                query,
                {
                    "number": 1,
                    "mode": 1,
                    "start": 1,
                    "end": 1,
                    "processing_status": 1,
                    "data.type": 1,
                    "xams_bookkeeping.science_run_id": 1,
                    "xams_bookkeeping.run_class": 1,
                    "xams_bookkeeping.source_type": 1,
                    "_id": 0,
                },
            )
            .sort("number", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        out: list[RunSummary] = []
        for doc in cursor:
            ps = doc.get("processing_status")
            dtypes = [d.get("type") for d in doc.get("data", []) if isinstance(d, dict)]
            xbk = self._bookkeeping(doc)
            out.append(
                RunSummary(
                    number=int(doc["number"]),
                    mode=doc.get("mode"),
                    start=doc.get("start"),
                    end=doc.get("end"),
                    processing_status=self._processing_status_value(ps),
                    has_raw_records=("raw_records" in dtypes),
                    has_events=("events" in dtypes or "event_info" in dtypes),
                    has_led_calibration=("led_calibration" in dtypes),
                    science_run_id=xbk.get("science_run_id") or "",
                    run_class=xbk.get("run_class") or "",
                    source_type=xbk.get("source_type") or "",
                )
            )
        return out, int(total)

    def delete_run_data_entries(self, run_id: int) -> dict[str, Any]:
        """Remove all data entries from the run document and reset processing_status."""
        result = self.runs.update_one(
            {"number": int(run_id)},
            {
                "$set": {
                    "data": [],
                    "processing_status": {"status": "deleted", "time": datetime.utcnow()},
                }
            },
        )
        return {"matched": result.matched_count, "modified": result.modified_count}

    def get_run_doc(self, run_id: int) -> dict[str, Any] :
        return self.runs.find_one({"number": int(run_id)}, {"_id": 0})

    def get_run_details(self, run_id: int) -> RunDetails :
        doc = self.get_run_doc(run_id)
        if not doc:
            return None

        entries = [self._normalize_data_entry(d) for d in doc.get("data", [])]
        return RunDetails(
            number=int(doc["number"]),
            mode=doc.get("mode"),
            start=doc.get("start"),
            end=doc.get("end"),
            tags=doc.get("tags", []),
            comments=doc.get("comments", []),
            processing_status=doc.get("processing_status"),
            data_entries=entries,
            raw_doc=doc,
        )

    def get_job_status(self, run_id: int) -> dict[str, Any]:
        doc = self.get_run_doc(run_id)
        if not doc:
            return {"found": False, "status": "missing_run"}
        ps = doc.get("processing_status")
        status = self._processing_status_value(ps)
        time_val = ps.get("time") if isinstance(ps, dict) else None
        host_val = ps.get("host") if isinstance(ps, dict) else None
        reason_val = ps.get("reason") if isinstance(ps, dict) else None
        return {
            "found": True,
            "run_id": run_id,
            "status": status,
            "time": time_val,
            "host": host_val,
            "reason": reason_val,
        }

    def append_processing_history(self, run_id: int, entry: dict[str, Any]) -> None:
        now = datetime.utcnow()
        payload = dict(entry or {})
        payload.setdefault("time", now)
        payload.setdefault("user", getpass.getuser())
        payload.setdefault("host", "stbc-i1")
        payload.setdefault("action", "dashboard_submit")
        payload.setdefault("status", "unknown")
        self.runs.update_one({"number": int(run_id)}, {"$push": {"processing_history": payload}})

    def _infer_run_class(self, mode: str) -> str:
        m = (mode or "").lower()
        if "led" in m:
            return "led"
        if "calib" in m or "source" in m:
            return "calibration"
        if "test" in m:
            return "test"
        return "science"

    def backfill_bookkeeping(
        self,
        science_run_id: str = "",
        run_class: str = "",
        source_type: str = "",
        run_id_min: Optional[int] = None,
        run_id_max: Optional[int] = None,
        run_ids: Optional[list[int]] = None,
        only_missing: bool = True,
        dry_run: bool = True,
        limit: int = 1500,
        actor: str = "dashboard",
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if run_ids:
            query["number"] = {"$in": [int(r) for r in run_ids]}
        else:
            num_q: dict[str, Any] = {}
            if run_id_min is not None:
                num_q["$gte"] = int(run_id_min)
            if run_id_max is not None:
                num_q["$lte"] = int(run_id_max)
            if num_q:
                query["number"] = num_q
        if only_missing:
            query["$or"] = [
                {"xams_bookkeeping": {"$exists": False}},
                {"xams_bookkeeping.science_run_id": {"$in": [None, ""]}},
            ]

        cursor = (
            self.runs.find(query, {"_id": 0, "number": 1, "mode": 1, "xams_bookkeeping": 1})
            .sort("number", -1)
            .limit(max(1, min(int(limit), 5000)))
        )
        docs = list(cursor)
        normalized_sr = self._normalize_sr(science_run_id or "")
        updates: list[dict[str, Any]] = []
        preview: list[dict[str, Any]] = []

        for doc in docs:
            rid = int(doc["number"])
            mode = doc.get("mode") or ""
            xbk = doc.get("xams_bookkeeping") if isinstance(doc.get("xams_bookkeeping"), dict) else {}
            before = {
                "science_run_id": (xbk.get("science_run_id") or ""),
                "run_class": (xbk.get("run_class") or ""),
                "source_type": (xbk.get("source_type") or ""),
            }
            after = dict(before)

            if normalized_sr and (not only_missing or not before["science_run_id"]):
                after["science_run_id"] = normalized_sr
            if run_class and (not only_missing or not before["run_class"]):
                after["run_class"] = run_class
            if source_type and (not only_missing or not before["source_type"]):
                after["source_type"] = source_type
            if not after["run_class"]:
                after["run_class"] = self._infer_run_class(mode)
            if not after["source_type"]:
                after["source_type"] = "none"

            changed = before != after
            preview.append(
                {
                    "run_id": rid,
                    "mode": mode,
                    "before": before,
                    "after": after,
                    "changed": changed,
                }
            )
            if changed:
                updates.append(
                    {
                        "run_id": rid,
                        "payload": {
                            "xams_bookkeeping.science_run_id": after["science_run_id"],
                            "xams_bookkeeping.run_class": after["run_class"],
                            "xams_bookkeeping.source_type": after["source_type"],
                            "xams_bookkeeping.last_backfilled_at": datetime.utcnow(),
                            "xams_bookkeeping.last_backfilled_by": actor,
                        },
                    }
                )

        applied = 0
        if not dry_run:
            for item in updates:
                res = self.runs.update_one({"number": item["run_id"]}, {"$set": item["payload"]})
                if res.modified_count > 0:
                    applied += 1

        return {
            "matched": len(docs),
            "candidate_updates": len(updates),
            "applied": applied,
            "dry_run": bool(dry_run),
            "only_missing": bool(only_missing),
            "normalized_science_run_id": normalized_sr,
            "preview": preview[:250],
        }

    def get_held_jobs(self) -> list[dict[str, Any]]:
        cmd = [
            "condor_q",
            getpass.getuser(),
            "-hold",
            "-af",
            "ClusterId",
            "ProcId",
            "BatchName",
            "QDate",
            "HoldReason",
        ]
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode != 0:
                return []
            rows = []
            for line in p.stdout.splitlines():
                parts = line.strip().split(None, 4)
                if len(parts) < 5:
                    continue
                rows.append(
                    {
                        "cluster_id": parts[0],
                        "proc_id": parts[1],
                        "batch_name": parts[2],
                        "qdate": parts[3],
                        "hold_reason": parts[4],
                    }
                )
            return rows
        except Exception:
            return []

    def get_queue_jobs(self, limit: int = 80) -> dict[str, Any]:
        status_map = {
            "0": "unexpanded",
            "1": "idle",
            "2": "running",
            "3": "removed",
            "4": "completed",
            "5": "held",
            "6": "transferring_output",
            "7": "suspended",
        }
        cmd = [
            "condor_q",
            getpass.getuser(),
            "-nobatch",
            "-af",
            "ClusterId",
            "ProcId",
            "JobStatus",
            "BatchName",
            "QDate",
        ]
        out_rows = []
        counts = {"idle": 0, "running": 0, "held": 0, "other": 0}
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode != 0:
                return {"counts": counts, "rows": []}
            for line in p.stdout.splitlines():
                parts = line.strip().split(None, 4)
                if len(parts) < 5:
                    continue
                st = status_map.get(parts[2], "other")
                if st in counts:
                    counts[st] += 1
                else:
                    counts["other"] += 1
                out_rows.append(
                    {
                        "cluster_id": parts[0],
                        "proc_id": parts[1],
                        "status": st,
                        "batch_name": parts[3],
                        "qdate": parts[4],
                    }
                )
            out_rows = sorted(out_rows, key=lambda r: (r["status"], r["cluster_id"]), reverse=True)[: max(1, limit)]
            return {"counts": counts, "rows": out_rows}
        except Exception:
            return {"counts": counts, "rows": []}
