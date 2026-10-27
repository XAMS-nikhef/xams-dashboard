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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

RAW_TYPES = frozenset({"raw_records", "raw_records_ext", "raw_records_sipm"})
NEVER_TYPES = frozenset({"live"})                    # never deleted by the data view, in any profile
MC_RUNS = (900000, 999999)
XAMS = Path("/data/xenon/xams_v2")


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
    links: list = field(default_factory=list)         # [(label, url)] in the page header
    min_run: int = 0                                  # runs below it are not shown


def private_profile(settings) -> Profile:
    return Profile(name="private", title="private", locations=[Location(Path(settings.strax_folder), "strax_data")],
                   state_dir=Path(settings.strax_folder), providers=list(settings.contexts), token=settings.token)


# ------------------------------------------------------------------------------------------------ production
def current_versions() -> list:
    """The corrections versions whose data count as current (XAMS_DASH_CURRENT_VERSIONS, default PROD0,v4)."""
    return [v.strip() for v in os.environ.get("XAMS_DASH_CURRENT_VERSIONS", "PROD0,v4").split(",") if v.strip()]


def production_providers(processed: Path) -> list:
    data_runs = [0, MC_RUNS[0] - 1]
    out = [{"name": v, "kind": "amstrax", "context": "xams",
            "kwargs": {"output_folder": str(processed), "corrections_version": v}, "runs": data_runs}
           for v in current_versions()]
    out.append({"name": "LED", "kind": "amstrax", "context": "xams_led", "kwargs": {"output_folder": str(processed)},
                "types": ["records_led", "led_calibration"], "runs": data_runs})
    out.append({"name": "MC (MC1)", "kind": "function", "path": str(Path(__file__).with_name("central_contexts.py")),
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
                   raw_rule=_live_on_stbc, on_delete=_remove_data_entry,
                   links=[("Old dashboard", "/"), ("Corrections", "/corrections"), ("Admin", "/admin")],
                   min_run=int(os.environ.get("XAMS_DASH_V3_MIN_RUN", "6000")))     # as the online processing
