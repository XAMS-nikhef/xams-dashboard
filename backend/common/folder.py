"""The user's strax folder: data sets (<run>-<data type>-<lineage hash>, strax's folder names; "_temp" = not finished),
their sizes, keep marks and deletion.

Deletion is limited to data-set folders directly inside the strax folder (names checked against the strax pattern,
resolved paths checked to lie in the folder), never a kept one, and every deletion is logged. Keep marks and the log
are small files in the folder itself: .dashboard_keep.json, .dashboard_deletions.log.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

NAME = re.compile(r"^(?P<run>\d{6})-(?P<dtype>[A-Za-z0-9_]+)-(?P<hash>[a-z0-9]{10})(?P<temp>_temp)?$")
KEEP_FILE = ".dashboard_keep.json"
LOG_FILE = ".dashboard_deletions.log"

_SIZES: dict = {}            # folder path -> (mtime, size, n_files)
SCAN_THREADS = int(os.environ.get("XAMS_DASH_SCAN_THREADS", "16"))   # parallel directory listings in scan()


@dataclass
class DataSet:
    name: str
    run: int
    dtype: str
    hash: str
    temp: bool
    size: int
    n_files: int
    mtime: float
    loc: int = 0                     # index of the profile location (folder) it is in

    @property
    def id(self) -> str:
        """Unique over a profile's locations: the name in the first location, "<loc>:<name>" in the others."""
        return self.name if self.loc == 0 else f"{self.loc}:{self.name}"


def split_id(ds_id: str) -> tuple[int, str]:
    loc, _, name = ds_id.rpartition(":")
    return (int(loc) if loc.isdigit() else 0), name


def parse(name: str):
    m = NAME.match(name)
    return m.groupdict() if m else None


def _size(path: Path) -> tuple[int, int, float]:
    st = path.stat()
    hit = _SIZES.get(str(path))
    if hit and hit[0] == st.st_mtime:
        return hit[1], hit[2], st.st_mtime
    size = n = 0
    with os.scandir(path) as it:
        for e in it:
            if e.is_file(follow_symlinks=False):
                size += e.stat(follow_symlinks=False).st_size
                n += 1
    _SIZES[str(path)] = (st.st_mtime, size, n)
    return size, n, st.st_mtime


def scan(folder: Path, loc: int = 0, min_run: int = 0) -> list[DataSet]:
    """All data sets in the folder (other files and folders are ignored); runs below min_run are skipped before
    their size is read."""
    found = []
    with os.scandir(folder) as it:
        for e in it:
            p = parse(e.name)
            if p is None or int(p["run"]) < min_run or not e.is_dir(follow_symlinks=False):
                continue
            found.append((e, p))
    # the sizes need one directory listing per data set: on NFS that is latency-bound (10k raw_records sets: ~3 min
    # serially, 30-10-2026), so list them in parallel
    with ThreadPoolExecutor(max_workers=SCAN_THREADS) as ex:
        sizes = list(ex.map(lambda ep: _size(Path(ep[0].path)), found))
    out = [DataSet(name=e.name, run=int(p["run"]), dtype=p["dtype"], hash=p["hash"], temp=bool(p["temp"]), size=size,
                   n_files=n, mtime=mtime, loc=loc) for (e, p), (size, n, mtime) in zip(found, sizes)]
    return sorted(out, key=lambda d: (d.run, d.dtype, -d.mtime))


def as_dict(d: DataSet) -> dict:
    return {**asdict(d), "id": d.id}


# ------------------------------------------------------------------------------------------------ keep marks
def load_keep(folder: Path) -> dict:
    f = Path(folder) / KEEP_FILE
    try:
        return json.loads(f.read_text()).get("keep", {})
    except (FileNotFoundError, ValueError):
        return {}


def set_keep(folder: Path, name: str, keep: bool, note: str = "") -> dict:
    """Keep mark of a data set (by its id) in the state folder `folder`."""
    if parse(split_id(name)[1]) is None:
        raise ValueError(f"not a data set name: {name}")
    marks = load_keep(folder)
    if keep:
        marks[name] = {"time": time.strftime("%Y-%m-%d %H:%M"), "user": getpass.getuser(), "note": note}
    else:
        marks.pop(name, None)
    f = Path(folder) / KEEP_FILE
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"keep": marks}, indent=1))
    tmp.replace(f)
    return marks


# ------------------------------------------------------------------------------------------------ deletion
def _target(folder: Path, name: str) -> Path:
    """The data-set folder `name` inside `folder`, or ValueError if it is not one (pattern, inside, a real folder)."""
    if parse(name) is None or "/" in name or name in (".", ".."):
        raise ValueError("not a data set name")
    base = Path(folder).resolve()
    p = base / name
    if p.is_symlink() or not p.is_dir():
        raise ValueError("no such data set folder")
    if p.resolve().parent != base:
        raise ValueError("outside the strax folder")
    return p


def delete(folder: Path, names: list, confirm: bool = False) -> dict:
    """Preview (confirm False) or delete data sets. Returns what is (or would be) deleted with sizes, and what is
    refused and why."""
    keep = load_keep(folder)
    ok, refused = [], []
    for name in dict.fromkeys(names):                       # unique, in order
        try:
            p = _target(folder, name)
        except ValueError as e:
            refused.append({"name": name, "reason": str(e)})
            continue
        if name in keep:
            refused.append({"name": name, "reason": "marked keep"})
            continue
        size, n, _ = _size(p)
        ok.append({"name": name, "size": size, "n_files": n})
    out = {"confirm": bool(confirm), "delete": ok, "refused": refused, "size": sum(x["size"] for x in ok),
           "deleted": [], "errors": []}
    if not confirm:
        return out
    log = Path(folder) / LOG_FILE
    for x in ok:
        try:
            shutil.rmtree(_target(folder, x["name"]))
            _SIZES.pop(str(Path(folder) / x["name"]), None)
            out["deleted"].append(x["name"])
            with open(log, "a") as f:
                f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "user": getpass.getuser(),
                                    "name": x["name"], "size": x["size"]}) + "\n")
        except Exception as e:                               # noqa: BLE001
            out["errors"].append({"name": x["name"], "error": str(e)})
    return out


def deletion_log(folder: Path, n: int = 200) -> list:
    f = Path(folder) / LOG_FILE
    if not f.exists():
        return []
    rows = []
    for line in f.read_text().splitlines()[-n:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[::-1]
