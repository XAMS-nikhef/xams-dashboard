# One dashboard for production and private: analysis

Status: report (2026-10-27), nothing built. Question: can the production dashboard become as informative as the
private one, with shared code instead of two separate apps?

## 1. Short answer

Yes. Both do the same five things: list runs, show a run's data sets with a status, explain the status, plot a data
set, and act on it (process, delete). They differ in only four places:

| | Production | Private |
|---|---|---|
| **Where the runs come from** | run database (`runs_gas`, `runs_mc`), with filters (science run, class, source, mode, processing status) | the strax folder (run documents read for information) |
| **Where the data sets are** | several storage locations + the `data[]` entries of the run document | one strax folder |
| **What "current" means** | what the installed amstrax makes with a corrections version (online, v4, PROD0, …; LED context; MC contexts) | what the user's analysis contexts make |
| **Actions** | process via auto-processing (condor as xamsdata, waiting list, history in the run document); delete all processed data of a run, also its `data[]` entries | (process later); delete per data set, keep marks, log |

Everything else (status per data set, "why?", plots, the run/data-set layout) can be one code base. In that view the
production dashboard is the private one with a different *profile*: run source = database, providers = the central
contexts per corrections version, actions = auto-processing and database-aware deletion.

## 2. What exists today

**Production** (`v2/app.py`, `backend/`, `v2/static/v2/`: ~2 900 lines):
- run browser from the database with filters; per run: Inspect (run document, data sets on disk with "loadable" and a
  reason), Plots (events, peaks, waveforms, LED calibration), Processing & Queue (submit, waiting list, held jobs, job
  logs); Corrections page (versions, coverage per run); Admin (bookkeeping backfill);
- "up to date" in the run list: only for `event_info`, only for the newest corrections version of the run
  (`processing_up_to_date`); per run a second, separate judgement of every data set (`scan_disk_availability`);
- both computed in the web process with amstrax contexts (cached 1 h): slow on first use; it says *that* a data set is
  "older", not *why*.

**Private** (`v2/private_app.py`, `backend/private/`, `v2/static/private/`: ~1 700 lines):
- status per data set for all types (current / outdated / unknown / incomplete), several providers side by side, each
  in its own process, cached on disk; "why?" (lineage diff); plots read straight from a data set's folder (any
  version); keep marks; deletion per data set with preview and log; Data / MC tabs; token.

Overlap: the run list, the data-set table, the status logic and the plots are three times the same idea
(`processing_up_to_date`, `scan_disk_availability`, `backend/private/lineage.py`) in two code bases.

## 3. Proposed structure

One app, one frontend (the private layout, which reads better), configured by a profile:

```
profile "production"                          profile "private"
  RunSource: Database (filters, data[])          RunSource: Folder (+ run documents, read-only)
  Locations: central storage folders             Locations: the user's strax folder
  Providers: central contexts per corrections     Providers: the user's analysis contexts
             version (+ LED, + MC per run)
  Actions:   Process = auto-processing            Actions:   Process = own condor jobs (later)
             Delete  = data set(s) + data[] entry            Delete  = data set(s), folder only
             Keep    = marks (xamsdata)                      Keep    = marks
  Extra pages: Corrections, Admin, Queue           Extra pages: —
```

Shared, used by both: data-set scan of a list of folders, providers + workers + cache (`lineage.py`), "why?"
(`whatchanged.py`), reading stored data (`stored.py`), deletion core (`folder.py`: names checked, only inside the
configured folders, log), the run list and data-set table, plots.

What production gains: status and "why?" for every data type (not only `event_info`), several corrections versions
side by side (a data set made with v4 is current if v4 is still an active version), plots of any stored version, the
size per run and per status, deletion per data set instead of all processed data of a run.

What the private one gains: the run filters of production (science run, class, source, mode), the job / queue panel
when its Process button comes.

## 4. Points that need care

- **Production is used by others.** Same approach as for the private mode: new page next to the old one (e.g. `/v3`)
  during a trial, the old one stays the default until you switch; then the old page and the duplicate status code go.
- **What counts as "current" in production.** Proposal: a list of *active* corrections versions in the settings (e.g.
  online, v4, PROD0); a data set is current if one of them makes it. Today only the newest version of a run counts.
- **Size.** The central processed folder has ~7 900 data sets (private: ~600). The background computation with an
  on-disk cache handles that; the first full pass takes longer (estimate: tens of minutes, then only what is new).
- **Deletion in production** must keep the run database consistent: deleting a data set also removes its `data[]`
  entry; raw and live data stay untouchable (as now, `KEEP_TYPES`). Per-data-set deletion is new for production:
  decide who may use it.
- **Where production keeps its files** (hash cache, keep marks, deletion log): in an xamsdata-owned place next to the
  processed data, not in user areas.
- **MC and LED**: production already has special contexts for simulated runs (corrections MC1 per run) and LED runs;
  they become providers limited to their runs (the same `runs` range mechanism the private MC provider uses).
- **Access**: production stays behind the tunnel as now; the private token stays for private.

## 5. Steps (one PR each, production unchanged until step 4)

1. **Shared core:** move `backend/private/` pieces that are not private (scan of several folders, providers / worker /
   cache, whatchanged, stored, deletion core) to `backend/common/`; private app uses them. No behaviour change.
2. **Production profile, backend:** database run source, central providers per active corrections version (+ LED,
   + MC), data sets from the storage locations joined with `data[]`; new API next to the old one.
3. **One frontend** with the profile switch; production page at `/v3` for the trial; Corrections, Admin and Queue
   linked from it.
4. **Switch:** after the trial `/` = the new page; old page and duplicate status code removed.
5. **Process button** for both (production: the existing submission; private: own condor jobs), using "why?" to pick
   what to process again.

Rough size: step 1 small, steps 2–3 the main work (production specifics: corrections versions, LED, MC, `data[]`),
step 4 mostly deletion of old code.

## 6. Decisions for you

1. Active corrections versions in production: which ones count as "current" (all registered, or a chosen list)?
2. Deletion per data set in production: allowed, and for whom (everyone with the tunnel, or only xamsdata operators)?
3. Keep marks in production: wanted?
4. Trial: how long side by side before the new page becomes the default?
