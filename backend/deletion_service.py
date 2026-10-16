from __future__ import annotations

import os
import shutil
from typing import Any

from .loadability import scan_disk_availability

# Never deleted by "delete data": the raw data (rebuilding them needs the live data) and the live data themselves.
# Only processed data are removed, so a run can always be reprocessed from what is kept.
KEEP_TYPES = frozenset({"live", "raw_records", "raw_records_ext", "raw_records_sipm"})


def delete_run_disk_data(run_id: int) -> dict[str, Any]:
    """Delete the processed-data directories found for run_id; raw and live data are kept.

    Uses the same scan as the loadability table, so it covers all storage locations; datasets whose type is in
    KEEP_TYPES are listed under "kept" and left alone.
    """
    rows = scan_disk_availability(run_id)
    deleted: list[str] = []
    kept: list[str] = []
    errors: list[dict[str, str]] = []

    seen: set[str] = set()
    for row in rows:
        dirpath = os.path.join(row["location"], row["dataset_dir"])
        if dirpath in seen:
            continue
        seen.add(dirpath)
        if row.get("type") in KEEP_TYPES:
            kept.append(dirpath)
            continue
        if not os.path.isdir(dirpath):
            continue
        try:
            shutil.rmtree(dirpath)
            deleted.append(dirpath)
        except Exception as exc:
            errors.append({"path": dirpath, "error": str(exc)})

    return {
        "scanned": len(rows),
        "deleted": deleted,
        "kept": kept,
        "errors": errors,
    }
