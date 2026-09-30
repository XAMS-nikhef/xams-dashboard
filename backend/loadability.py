from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List

from .config import settings

TARGET_TYPES = (
    "raw_records",
    "raw_records_ext",
    "raw_records_sipm",
    "peaks",
    "peak_basics",
    "events",
    "event_info",
    "event_basics",
    "event_positions",
    "records_led",
    "led_calibration",
)


def _storage_locations() -> List[str]:
    paths = []
    try:
        import amstrax  # type: ignore

        for p in getattr(amstrax.contexts, "PATHS_TO_REGISTER", []):
            if isinstance(p, str):
                paths.append(p)
    except Exception:
        pass

    paths.extend([
        settings.stbc_output_dir,
        "/data/xenon/xams_v2/xams_raw_records",
        "/data/xenon/xams_v2/xams_processed",
        "/home/xams/data/xams_processed",
    ])

    unique = []
    seen = set()
    for p in paths:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    return unique


def _parse_dataset_dirname(dirname: str) -> Dict[str, Any]:
    # expected shape: 007375-events-abcdefghij
    parts = dirname.split("-")
    if len(parts) < 3:
        return {}
    run_prefix = parts[0]
    lineage = parts[-1]
    data_type = "-".join(parts[1:-1])
    return {"run_prefix": run_prefix, "type": data_type, "lineage_hash": lineage}


def _run_db_data_metadata(run_id: int) -> Dict[tuple[str, str], Dict[str, Any]]:
    out: Dict[tuple[str, str], Dict[str, Any]] = {}
    try:
        import amstrax  # type: ignore

        doc = amstrax.get_mongo_collection().find_one({"number": int(run_id)}, {"data": 1, "_id": 0}) or {}
        for e in doc.get("data", []):
            if not isinstance(e, dict):
                continue
            dtype = str(e.get("type") or "")
            lineage = str(e.get("lineage_hash") or e.get("lineage") or e.get("hash") or "")
            if not dtype:
                continue
            out[(dtype, lineage)] = {
                "db_host": e.get("host"),
                "db_location": e.get("location"),
                "db_corrections_version": e.get("corrections_version"),
                "db_amstrax_version": e.get("amstrax_version"),
                "db_is_online": e.get("is_online"),
            }
            if (dtype, "") not in out:
                out[(dtype, "")] = out[(dtype, lineage)]
    except Exception:
        pass
    return out


_CTX_CACHE: Dict[Any, Any] = {}
_CTX_TTL_S = 3600


def _context(corrections_version=None, led=False):
    """amstrax context for a corrections version (None = default), cached for an hour."""
    key = ("led" if led else "xams", corrections_version or None)
    hit = _CTX_CACHE.get(key)
    if hit and time.time() - hit[0] < _CTX_TTL_S:
        return hit[1]
    import amstrax  # type: ignore

    kwargs = {"output_folder": settings.stbc_output_dir}
    if corrections_version and corrections_version != "online":
        kwargs["corrections_version"] = corrections_version
    factory = amstrax.contexts.xams_led if led else amstrax.contexts.xams
    st = factory(**kwargs)
    _CTX_CACHE[key] = (time.time(), st)
    return st


def _expected(run6: str, dtype: str, corrections_version=None):
    """(lineage_hash, is_stored) of dtype for this run in the context of a corrections version."""
    try:
        st = _context(corrections_version, led=dtype in ("records_led", "led_calibration"))
    except Exception:
        return None, False
    try:
        lineage = st.key_for(run6, dtype).lineage_hash
    except Exception:
        lineage = None
    try:
        stored = bool(st.is_stored(run6, dtype))
    except Exception:
        stored = False
    return lineage, stored


_LINEAGE_CACHE: Dict[Any, Any] = {}


def _current_lineage(run6: str, dtype: str, corrections_version=None):
    """Lineage the installed amstrax makes for dtype with a corrections version (cached with the contexts)."""
    key = (run6, dtype, corrections_version or None)
    hit = _LINEAGE_CACHE.get(key)
    if hit and time.time() - hit[0] < _CTX_TTL_S:
        return hit[1]
    try:
        st = _context(corrections_version, led=dtype in ("records_led", "led_calibration"))
        lineage = st.key_for(run6, dtype).lineage_hash
    except Exception:
        lineage = None
    _LINEAGE_CACHE[key] = (time.time(), lineage)
    return lineage


def _version_key(v: str):
    if v == "online":
        return (0, 0, v)
    m = re.match(r"^v(\d+)$", v)
    return (1, int(m.group(1)), v) if m else (2, 0, v)


def processing_up_to_date(run_id: int, data_entries: List[Dict[str, Any]], dtype: str = "event_info") -> Dict[str, Any]:
    """Is the newest-version product of a run what the installed amstrax would make now?

    status: "current"  - a stored entry of the newest corrections version has the current lineage
            "outdated" - entries of that version exist, but none with the current lineage (reprocess)
            "none"     - no entry of this data type
    """
    run6 = "{:06d}".format(int(run_id))
    by_version: Dict[str, set] = {}
    for e in data_entries or []:
        if not isinstance(e, dict) or e.get("type") != dtype:
            continue
        v = str(e.get("corrections_version") or "online")
        by_version.setdefault(v, set()).add(str(e.get("lineage_hash") or e.get("lineage") or e.get("hash") or ""))
    if not by_version:
        return {"run_id": int(run_id), "status": "none", "version": None}
    newest = sorted(by_version, key=_version_key)[-1]
    current = _current_lineage(run6, dtype, None if newest == "online" else newest)
    if current is None:
        return {"run_id": int(run_id), "status": "unknown", "version": newest}
    status = "current" if current in by_version[newest] else "outdated"
    return {"run_id": int(run_id), "status": status, "version": newest, "current_lineage": current}


def scan_disk_availability(run_id: int) -> List[Dict[str, Any]]:
    """Datasets of a run on disk, each judged against the corrections version it was made with.

    A dataset is loadable when its lineage equals what the installed amstrax
    produces for the corrections version recorded in the run DB (or for the default
    context when no version was recorded).
    """
    run6 = "{:06d}".format(int(run_id))
    rows = []
    db_meta = _run_db_data_metadata(run_id)
    expected: Dict[tuple, tuple] = {}

    def _exp(dtype, version):
        k = (dtype, version or None)
        if k not in expected:
            expected[k] = _expected(run6, dtype, version)
        return expected[k]

    for base in _storage_locations():
        if not os.path.isdir(base):
            continue
        try:
            children = os.listdir(base)
        except Exception:
            continue

        for d in children:
            if not d.startswith(run6 + "-"):
                continue
            meta = _parse_dataset_dirname(d)
            if not meta:
                continue
            if meta["type"] not in TARGET_TYPES:
                continue

            full = os.path.join(base, d)
            n_files = 0
            size_mb = 0.0
            try:
                for root, _, files in os.walk(full):
                    for f in files:
                        n_files += 1
                        fp = os.path.join(root, f)
                        try:
                            size_mb += os.path.getsize(fp) / (1024 * 1024)
                        except Exception:
                            pass
            except Exception:
                pass

            md = db_meta.get((meta["type"], meta["lineage_hash"])) or {}
            version = md.get("db_corrections_version")
            exp_lineage, stored = _exp(meta["type"], version)
            matched_version = version
            if exp_lineage != meta["lineage_hash"] and version:
                # e.g. peak_basics made in a v4 job but identical to the default lineage
                d_lineage, d_stored = _exp(meta["type"], None)
                if d_lineage == meta["lineage_hash"]:
                    exp_lineage, stored, matched_version = d_lineage, d_stored, None
            loadable = bool(n_files > 0 and exp_lineage is not None and exp_lineage == meta["lineage_hash"])
            rows.append(
                {
                    "type": meta["type"],
                    "lineage_hash": meta["lineage_hash"],
                    "current_lineage_hash": exp_lineage,
                    "location": base,
                    "dataset_dir": d,
                    "n_files": n_files,
                    "size_mb": round(size_mb, 2),
                    "loadable": loadable,
                    "is_stored_for_type": stored,
                    "reason": _reason(
                        n_files=n_files,
                        in_db=bool(md),
                        version=matched_version,
                        expected=exp_lineage,
                        disk_lineage=meta["lineage_hash"],
                    ),
                    "db_host": md.get("db_host"),
                    "db_location": md.get("db_location"),
                    "db_corrections_version": version,
                    "db_amstrax_version": md.get("db_amstrax_version"),
                    "db_is_online": md.get("db_is_online"),
                }
            )

    rows.sort(key=lambda r: (r["type"], r["lineage_hash"], r["location"]))
    return rows


def check_is_stored(run_id: int, data_type: str) -> bool:
    """Ask the current amstrax context directly whether a data type is stored for a run."""
    try:
        import amstrax  # type: ignore

        run6 = "{:06d}".format(int(run_id))
        st = amstrax.contexts.xams(output_folder=settings.stbc_output_dir)
        return bool(st.is_stored(run6, data_type))
    except Exception:
        return False


def _reason(n_files: int, in_db: bool, version, expected, disk_lineage: str) -> str:
    ctx = "corrections {}".format(version) if version else "the default (online) context"
    if n_files == 0:
        return "directory exists but empty"
    if expected is None:
        return "could not build the amstrax context for {}".format(ctx)
    if expected == disk_lineage:
        return "OK: loadable with {}".format(ctx)
    if not in_db:
        return "not registered in the run DB; not made by the installed amstrax with {}".format(ctx)
    return ("older product: the installed amstrax makes a different lineage with {} "
            "(plugin or option changed since); reprocess to update").format(ctx)
