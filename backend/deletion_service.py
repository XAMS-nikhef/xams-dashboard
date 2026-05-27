from __future__ import annotations

import os
import shutil
from typing import Any

from .loadability import scan_disk_availability


def delete_run_disk_data(run_id: int) -> dict[str, Any]:
    """Delete every on-disk data directory found for run_id.

    Uses the same scan as the loadability table so it covers all
    storage locations (raw, processed, LED, ...).
    """
    rows = scan_disk_availability(run_id)
    deleted: list[str] = []
    errors: list[dict[str, str]] = []

    seen: set[str] = set()
    for row in rows:
        dirpath = os.path.join(row["location"], row["dataset_dir"])
        if dirpath in seen:
            continue
        seen.add(dirpath)
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
        "errors": errors,
    }
