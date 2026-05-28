from __future__ import annotations

import os
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


def scan_disk_availability(run_id: int) -> List[Dict[str, Any]]:
    run6 = "{:06d}".format(int(run_id))
    rows = []
    current_lineage = {}
    type_is_stored = {}
    db_meta = _run_db_data_metadata(run_id)

    try:
        import amstrax  # type: ignore

        st = amstrax.contexts.xams(output_folder=settings.stbc_output_dir)
        st_led = None
        try:
            st_led = amstrax.contexts.xams_led(output_folder=settings.stbc_output_dir)
        except Exception:
            st_led = None
        run6 = "{:06d}".format(int(run_id))
        for t in TARGET_TYPES:
            ctx = st_led if (t in ("records_led", "led_calibration") and st_led is not None) else st
            try:
                type_is_stored[t] = bool(ctx.is_stored(run6, t))
            except Exception:
                type_is_stored[t] = False
            try:
                current_lineage[t] = ctx.key_for(run6, t).lineage_hash
            except Exception:
                current_lineage[t] = None
    except Exception:
        for t in TARGET_TYPES:
            type_is_stored[t] = False
            current_lineage[t] = None

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

            md = db_meta.get((meta["type"], meta["lineage_hash"])) or db_meta.get((meta["type"], "")) or {}
            rows.append(
                {
                    "type": meta["type"],
                    "lineage_hash": meta["lineage_hash"],
                    "current_lineage_hash": current_lineage.get(meta["type"]),
                    "location": base,
                    "dataset_dir": d,
                    "n_files": n_files,
                    "size_mb": round(size_mb, 2),
                    "loadable": bool(
                        n_files > 0
                        and type_is_stored.get(meta["type"], False)
                        and current_lineage.get(meta["type"]) == meta["lineage_hash"]
                    ),
                    "is_stored_for_type": type_is_stored.get(meta["type"], False),
                    "reason": _reason(
                        n_files=n_files,
                        dtype=meta["type"],
                        disk_lineage=meta["lineage_hash"],
                        current_lineage=current_lineage.get(meta["type"]),
                        is_stored=type_is_stored.get(meta["type"], False),
                    ),
                    "db_host": md.get("db_host"),
                    "db_location": md.get("db_location"),
                    "db_corrections_version": md.get("db_corrections_version"),
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


def _reason(n_files: int, dtype: str, disk_lineage: str, current_lineage: str, is_stored: bool) -> str:
    if n_files == 0:
        return "directory exists but empty"
    if not is_stored:
        return "on disk, but not stored in current context ({})".format(dtype)
    if current_lineage != disk_lineage:
        return "on disk, but lineage mismatch with current context"
    return "loadable with current context"
