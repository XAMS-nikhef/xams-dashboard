"""Read a stored data set directly from its folder (strax's file storage), without a context: plots of any version
in the folder, current or not."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def read(folder: Path, name: str, max_rows: int = 100000, fields=None) -> np.ndarray:
    """Up to max_rows rows of the data set `name` (chunks in order), only `fields` if given."""
    import strax
    path = str(Path(folder) / name)
    be = strax.FileSytemBackend()
    md = be.get_metadata(path)
    dtype = strax.io.literal_eval(md["dtype"]) if isinstance(md["dtype"], str) else md["dtype"]
    dtype = np.dtype([tuple(x) if not isinstance(x, tuple) else x for x in dtype])
    out, n = [], 0
    for ci in md["chunks"]:
        if not ci.get("n"):
            continue
        a = be._read_chunk(path, ci, dtype, md["compressor"])
        if fields:
            a = a[[f for f in fields if f in a.dtype.names]]
        out.append(a[: max_rows - n])
        n += len(out[-1])
        if n >= max_rows:
            break
    if not out:
        return np.zeros(0, dtype=dtype)
    return np.concatenate(out)


def metadata(folder: Path, name: str) -> dict:
    import strax
    md = strax.FileSytemBackend().get_metadata(str(Path(folder) / name))
    keep = ("run_id", "data_type", "data_kind", "lineage_hash", "strax_version", "writing_ended", "compressor")
    out = {k: md.get(k) for k in keep if k in md}
    out["n_rows"] = int(sum(c.get("n", 0) for c in md.get("chunks", [])))
    out["n_chunks"] = len(md.get("chunks", []))
    lin = md.get("lineage") or {}
    out["lineage"] = {k: v[:2] for k, v in lin.items()} if isinstance(lin, dict) else {}
    return out
