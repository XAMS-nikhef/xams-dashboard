"""Profiles of the data view: what differs between the private dashboard and the production page (/v3).

    private      the user's strax folder; providers = the user's analysis contexts; any data set may be deleted
                 (not kept ones); state files in the strax folder; token
    production   the central folders; providers = amstrax with the current corrections versions (+ LED, + MC);
                 only outdated / incomplete data sets may be deleted, not kept ones, and their data[] entry is removed
                 from the run document; raw records only when the run's live data are on STBC (they can be rebuilt);
                 live data never; state files in an xamsdata folder; no token (behind the tunnel as before)
"""
from __future__ import annotations

import os
import pwd
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

RAW_TYPES = frozenset({"raw_records", "raw_records_ext", "raw_records_sipm"})
NEVER_TYPES = frozenset({"live"})                    # never deleted by the data view, in any profile
MC_RUNS = (900000, 999999)
XAMS = Path("/data/xenon/xams_v2")
LIVE_NAMES = frozenset({"live_data", "live_mc"})     # folders of live data (DAQ, simulated): never managed privately


@dataclass
class Location:
    path: Path
    label: str
    raw: bool = False                                # raw records: deletable only under the raw rule


@dataclass
class Profile:
    name: str
    title: str
    locations: list
    state_dir: Path
    providers: list
    delete_statuses: frozenset | None = None          # statuses that may be deleted (None: any)
    token: str = ""
    raw_rule: Callable | None = None                  # (dataset) -> None if raw may go, else the reason it may not
    on_delete: Callable | None = None                 # (dataset, location) -> note, after a data set is deleted
    # (location path) -> None if this server may delete there, else why not (read-only); checked at every deletion
    location_check: Callable | None = None
    links: list = field(default_factory=list)         # [(label, url)] in the page header
    min_run: int = 0                                  # runs below it are not shown
    # deletion guards (production): an outdated data set (not raw) only when the same run has a current one of the
    # same type (a wrong current-versions setting makes everything "outdated"); one action at most this fraction of
    # the data sets / bytes (not raw) unless confirmed separately (None: no limit)
    require_current: bool = False
    bulk_limit: float | None = None
    # processing (set by the app that hosts the page; None: no Process button)
    submit: Callable | None = None                    # (run_ids, targets, corrections_version) -> result dict
    submit_options: Callable | None = None            # () -> {targets, corrections_versions, default_version, ...}
    jobs: Callable | None = None                      # () -> {run: job state} (condor / waiting list)
    # () -> may this request act (submit, delete)? None: yes (private: the token already decided). The page then
    # hides the action buttons; the server refuses the actions itself (v2/app.py _check_key)
    can_act: Callable | None = None
    # the settings page (gear): None = the folders shown read-only; else a backend.private.setup.Setup
    setup: object | None = None
    # () -> providers now, or None to keep the current ones (production: versions from the run database)
    refresh_providers: Callable | None = None


def private_location_problem(path, xams: Path = XAMS, uid: int | None = None) -> str | None:
    """Why a private dashboard may not delete in this folder (it is then shown read-only), or None.

    Only the user's own folders: not live data (live_data, live_mc, anywhere), not the central folders of xams_v2 (all
    but users/), not a folder owned by someone else (e.g. another user's area). The path is resolved first, so a
    symlink into a central folder counts as that folder."""
    try:
        rp = Path(path).resolve()
        st = rp.stat()
    except OSError:
        return None                                  # not there (yet): nothing to delete
    if LIVE_NAMES & set(rp.parts):
        return "live data are never deleted here"
    try:
        rel = rp.relative_to(Path(xams).resolve())
        if not rel.parts or rel.parts[0] != "users":
            return "a central XAMS folder (only the central dashboard manages it)"
    except ValueError:
        pass                                         # outside xams_v2: only the owner rule below
    if st.st_uid != (os.getuid() if uid is None else uid):
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        return f"not your folder (owner {owner})"
    return None


SHARED = "a shared folder: read-only on this dashboard"


def folder_owner(path) -> str:
    try:
        return pwd.getpwuid(Path(path).stat().st_uid).pw_name
    except (OSError, KeyError):
        return Path(path).name


def private_profile(settings) -> Profile:
    """The user's strax folder and, if set, the folders of their private MC (xams-sim reconstruction and raw records),
    and other users' shared folders: listed, always read-only here (no deletions; state files stay in strax_folder)."""
    locs = [Location(Path(settings.strax_folder), "strax_data")]
    if getattr(settings, "mc_processed_folder", None):
        locs.append(Location(Path(settings.mc_processed_folder), "mc_processed"))
    if getattr(settings, "mc_raw_folder", None):
        locs.append(Location(Path(settings.mc_raw_folder), "mc_raw_records", raw=True))
    shared = set()
    for p in getattr(settings, "shared_folders", None) or []:
        p = Path(p)
        label = f"shared: {folder_owner(p)}"
        while any(x.label == label for x in locs):
            label += "'"
        locs.append(Location(p, label))
        shared.add(str(p))

    def check(path):
        return SHARED if str(path) in shared else private_location_problem(path)

    return Profile(name="private", title="private", locations=locs,
                   state_dir=Path(settings.strax_folder), providers=list(settings.contexts), token=settings.token,
                   location_check=check)


# ------------------------------------------------------------------------------------------------ production
# Corrections workflow (amstrax_files docs/corrections_workflow.md, 2026-11-27): the run database says which versions
# are current, daq.settings {name: "current_corrections_versions", value: ["PROD6", "ONLINE", ...]} and
# {name: "online_corrections_version", value: "ONLINE"}. Changing them needs no restart (read at most once a minute).
# Without the documents (or without the database) the environment variables below are used, as before.
SETTING_CURRENT = "current_corrections_versions"
SETTING_ONLINE = "online_corrections_version"
SETTINGS_TTL = 60.0
_settings_cache: dict = {}


def db_setting(name, coll=None, now=None):
    """Value of daq.settings {name: <name>} (cached SETTINGS_TTL s), or None if absent or the database is unreadable."""
    now = time.monotonic() if now is None else now
    hit = _settings_cache.get(name)
    if coll is None and hit and now - hit[0] < SETTINGS_TTL:
        return hit[1]
    try:
        if coll is None:
            import amstrax  # type: ignore
            coll = amstrax.get_mongo_client()["daq"]["settings"]
        doc = coll.find_one({"name": name})
        value = doc.get("value") if doc else None
    except Exception:                                        # noqa: BLE001
        return hit[1] if hit else None                        # keep the last known value
    _settings_cache[name] = (now, value)
    return value


def _names(value) -> list:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def current_versions(coll=None) -> list:
    """The corrections versions whose data count as current: daq.settings current_corrections_versions, else
    XAMS_DASH_CURRENT_VERSIONS (default PROD0,v4)."""
    return (_names(db_setting(SETTING_CURRENT, coll))
            or _names(os.environ.get("XAMS_DASH_CURRENT_VERSIONS", "PROD0,v4")))


def submit_default_version(coll=None) -> str:
    """Default corrections version for submissions: XAMS_AUTOPROC_CORRECTIONS if set to a version; if unset or 'db',
    the online version of the run database (daq.settings online_corrections_version), else ONLINE."""
    env = os.getenv("XAMS_AUTOPROC_CORRECTIONS", "db").strip()
    if env and env != "db":
        return env
    return str(db_setting(SETTING_ONLINE, coll) or "ONLINE")


def amstrax_paths() -> dict:
    """Override: corrections version -> amstrax folder (XAMS_DASH_AMSTRAX_PATHS="PROD6=/.../amstrax_versioned/v11,...").
    Normally not needed: the run database says which amstrax made each version (versions_from_rundb)."""
    out = {}
    for item in os.environ.get("XAMS_DASH_AMSTRAX_PATHS", "").split(","):
        if "=" in item:
            v, path = item.split("=", 1)
            if v.strip() and path.strip():
                out[v.strip()] = path.strip()
    return out


def version_days() -> float:
    """A corrections version counts while production processed data with it in the last N days."""
    return float(os.environ.get("XAMS_DASH_VERSION_DAYS", "90"))


def versions_from_rundb(days: float | None = None, coll=None) -> list | None:
    """[(corrections version, amstrax path or None)] of the production processing of the last `days` days, newest
    first, from the data[] entries of the run documents (process.py writes corrections_version and amstrax_path).
    The path is the one of the version's newest entry. None if the run database cannot be read."""
    import datetime as _dt
    days = version_days() if days is None else days
    try:
        if coll is None:
            import amstrax  # type: ignore
            coll = amstrax.get_run_collection(1)
        since = _dt.datetime.utcnow() - _dt.timedelta(days=days)
        rows = list(coll.aggregate([
            {"$match": {"data.time": {"$gte": since}}},
            {"$unwind": "$data"},
            {"$match": {"data.time": {"$gte": since}, "data.corrections_version": {"$type": "string"}}},
            {"$sort": {"data.time": -1}},
            {"$group": {"_id": "$data.corrections_version", "path": {"$first": "$data.amstrax_path"},
                        "last": {"$first": "$data.time"}}},
            {"$sort": {"last": -1}}]))
    except Exception:                                        # noqa: BLE001
        return None
    return [(r["_id"], r.get("path")) for r in rows if r.get("_id")]


def production_providers(processed: Path, found: list | None = None) -> list:
    """amstrax providers per corrections version, each with the amstrax that made it: the versions production used
    in the last XAMS_DASH_VERSION_DAYS days (run database) plus XAMS_DASH_CURRENT_VERSIONS (always; the whole list
    when the run database cannot be read). A new production shows up by itself."""
    data_runs = [0, MC_RUNS[0] - 1]
    if found is None:
        found = versions_from_rundb() or []
    paths = {v: p for v, p in found}
    paths.update(amstrax_paths())
    versions = [v for v, _ in found] + [v for v in current_versions() if v not in dict(found)]
    out = []
    for v in versions:
        path = paths.get(v)
        prov = {"name": v, "kind": "amstrax", "context": "xams",
                "kwargs": {"output_folder": str(processed), "corrections_version": v, "event_structure_v2": True},
                "runs": data_runs}
        if path and (Path(path) / "amstrax").is_dir():
            prov["amstrax_path"] = str(path).rstrip("/")
        out.append(prov)
    out.append({"name": "LED", "kind": "amstrax", "context": "xams_led", "kwargs": {"output_folder": str(processed)},
                "types": ["records_led", "led_calibration"], "runs": data_runs})
    out.append({"name": "MC (MC2)", "kind": "function", "path": str(Path(__file__).with_name("central_contexts.py")),
                "call": "mc", "args": ["{run}"], "runs": list(MC_RUNS)})
    return out


def _live_on_stbc(d) -> str | None:
    """None if the run's live data are on STBC (raw records can be rebuilt), else why not."""
    try:
        import amstrax  # type: ignore
        doc = amstrax.get_run_collection(d.run).find_one({"number": d.run}, {"data": 1}) or {}
    except Exception as e:                                   # noqa: BLE001
        return f"run database not reachable ({str(e)[:80]})"
    for e in doc.get("data", []):
        if isinstance(e, dict) and e.get("type") == "live" and e.get("host") == "stbc":
            if (Path(str(e.get("location"))) / f"{d.run:06d}").is_dir():
                return None
    return "raw records: the run's live data are not on STBC, so they could not be rebuilt"


def _remove_data_entry(d, loc) -> str:
    """Remove the data[] entry of a deleted data set from the run document (type, lineage hash, location)."""
    import amstrax  # type: ignore
    coll = amstrax.get_run_collection(d.run)
    where = [str(loc.path), str(loc.path) + "/"]
    r = coll.update_one({"number": d.run},
                        {"$pull": {"data": {"type": d.dtype, "lineage_hash": d.hash, "location": {"$in": where}}}})
    return "data[] entry removed" if r.modified_count else "no data[] entry for it"


def production_profile() -> Profile:
    processed = Path(os.environ.get("XAMS_STBC_OUTPUT_DIR", XAMS / "xams_processed"))
    locs = [Location(processed, "xams_processed"),
            Location(XAMS / "xams_raw_records", "xams_raw_records", raw=True),
            Location(XAMS / "mc_processed", "mc_processed"),
            Location(XAMS / "mc_raw_records", "mc_raw_records", raw=True)]
    return Profile(name="production", title="v3 (trial)", locations=[x for x in locs if x.path.is_dir()],
                   state_dir=Path(os.environ.get("XAMS_DASH_STATE_DIR", XAMS / "dashboard_state")),
                   providers=production_providers(processed), delete_statuses=frozenset({"outdated", "incomplete"}),
                   raw_rule=_live_on_stbc, on_delete=_remove_data_entry, require_current=True, bulk_limit=0.05,
                   links=[("Old dashboard", "/"), ("Corrections", "/corrections"), ("Admin", "/admin")],
                   min_run=int(os.environ.get("XAMS_DASH_V3_MIN_RUN", "6000")),     # as the online processing
                   refresh_providers=lambda: _refresh(processed))


def _refresh(processed: Path) -> list | None:
    """The providers again (a new production, another amstrax); None when the run database cannot be read (keep)."""
    found = versions_from_rundb()
    return None if found is None else production_providers(processed, found)
