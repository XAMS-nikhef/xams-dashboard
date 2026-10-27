# Private dashboard: plan

Status (2026-10-27): step 1 built (XAMS-nikhef/xams-dashboard#15), launcher tile in XAMS-nikhef/xams-launcher#2;
the rest is plan.

## 1. Goal

A dashboard for the processed data in a user's own area on STBC, next to the production dashboard, the same way
xams-sim has a private simulation app next to the production one ("Simulations (private)" in the launcher).

- Private processed data (made with the user's own context, gains or settings) is never in the run documents
  (`data[]`), so the production dashboard cannot show it.
- These folders grow fast (`measurements/strax_data` of one user: 107 runs, 610 data sets, 25 GB): the user needs to
  see what is there, what is outdated, and delete it.
- Any XAMS user on STBC must be able to set up the same thing for their own account.

## 2. Production is not affected

- **Private mode is off unless a private settings file is given.** The production dashboard (xamsdata, port 8070) has
  none and keeps reading run documents and `data[]` exactly as now.
- **Separate processes:** own account, own port, own screen. Restarting or breaking a private app does nothing to
  production.
- **No writes to production:** the private app reads the run database only; it deletes only inside the user's own
  configured folders. The existing production delete (`backend/deletion_service.py`) is not changed.
- **Shared code is the only risk.** The private mode lives in the same repository, so a `git pull` as xamsdata brings
  the new code to production even though it does not use it. Therefore:
  - private parts in their own modules (`backend/private/`, own templates), minimal changes to shared code;
  - tests that production mode behaves as before (run list, run detail, loadability, submit);
  - the private app runs from the user's own checkout first; production is updated only on explicit OK, after a
    trial period.

## 3. Private dashboard

### 3.1 Data tab

- **One folder:** `strax_folder` (for acolijn: `/data/xenon/xams_v2/users/acolijn/measurements/strax_data`).
- **Run list from the folder:** scan the directory names `<run>-<data_type>-<hash>`. Run information (source, mode,
  start, comments, `sc_snapshot`) from the run database, read-only.
- **Per run:** data types, versions (hashes), size per data set, and a status per data set:
  - *current*: the hash equals the one the user's context would make now (`st.key_for(run, data_type)`);
  - *outdated*: another hash of a data type that the context also makes (old gains, old settings);
  - *other*: a data type the context does not know.
- **Folder header:** total size, size of the outdated data sets.
- **Plots and loadability:** as in the production dashboard (event plots: S1/S2, drift time, xy), with the user's
  context.

### 3.2 MC tab

The same views as for data, for the user's private simulations (xams-sim, numbers 990000-999999):

- private MC has no database entry: its run document is a file next to the raw records (`mc_raw_folder`, read via
  amstrax `RUNDOC_DIRS`, as `backend/loadability.py` does for production MC);
- reconstruction in `mc_processed_folder`; status, plots and loadability as in the production dashboard's MC handling
  (`for_mc_run`, corrections MC1), with the folders from the settings instead of the fixed `MC_RAW` /
  `MC_PROCESSED`.

### 3.3 What changed

Per outdated data set: why it is outdated, before anything is processed again or deleted. The stored data set's
lineage (its metadata) is compared with the lineage the provider that makes it would use now (`st.key_for(run,
type).lineage`, in the provider's own process like the hashes):

- per plugin in the chain: **version** changes (e.g. PeakPositions 1.2.26 → 2.1.0) and **option** changes, old → new
  value (e.g. `pos_rec_params_v0` → `pos_rec_map_v1`, a gain file, a `processing.json` setting);
- plugins that are new or gone in the chain;
- whether the data type is outdated **only through a dependency** (e.g. `event_basics` through `peak_positions`) or
  also through its own plugin;
- values compared after JSON normalisation (lists vs tuples are no change).

Shown in the run's data-set table (a "why?" next to the status) and in the tooltips of the run list. (A summary
panel over the folder was tried and dropped, 2026-10-27.) Cached with the hashes (same fingerprint).

Example (run 7720, SR2026.2, checked by hand 2026-10-27): `peaks`, `peak_basics`, `events` current; `peak_positions`
outdated (PeakPositions 1.2.26 → 2.1.0: correlation method with `pos_rec_params_v0` → `pos_rec_map_v1`);
`event_basics` outdated through `peak_positions` and its own version 1.6 → 1.7. Gains and settings unchanged: only
x, y differ.

### 3.4 Process button

Shown greyed out ("later"). Later: submit private processing as condor jobs under the user's own account (limit on
the number of jobs from the settings). Builds on 3.3: select outdated data sets (or one reason of the summary),
process them again with the provider that makes them current (strax reuses the current parts of the chain), then
offer to delete the old versions.

### 3.5 Delete

- Per data set, per version (hash), per run; bulk "delete all outdated" (optionally: older than N days).
- Always first a list with sizes, then a confirmation.
- Only inside `strax_folder` and `mc_processed_folder`; never MC raw records (a whole MC run is deleted with
  `xamssim delete-run`, xams-sim plan S10).
- **Keep marks:** a version can be marked "keep" (e.g. data behind a note); bulk delete skips it. Marks stored in a
  small file in the folder (`.dashboard_keep.json`).
- Every deletion logged (`.dashboard_deletions.log` in the folder: time, user, path, size).

## 4. For every user

### 4.1 Settings file

One file per user on STBC, read by both private apps (dashboard and xams-sim), e.g. `~/.xams/private.json`
(a few kB; the home quota is small, so nothing else goes there):

| key | meaning |
|---|---|
| `strax_folder` | private processed data |
| `mc_raw_folder`, `mc_processed_folder` | private MC raw records (+ run documents) and reconstruction |
| `sim_data` | xams-sim data folder (`XAMSSIM_DATA`) of the private simulation app |
| `context` | how lineage and plots are built: `{"kind": "amstrax", "name": ..., "corrections_version": ..., "config": {...}}` or `{"kind": "function", "path": ".../lib/xams_sr.py", "call": "context", "args": ["P1"]}` |
| `ports` | remote ports of the private dashboard and simulation app |
| `token` | secret of the private apps (4.3) |
| `conda_env`, `checkouts` | environment and the user's checkouts of xams-dashboard / xams-sim |
| `max_jobs` | for the Process button (later) |

### 4.2 Launcher: Settings tile

A form in the launcher (XAMS-nikhef/xams-launcher) instead of editing `config.sh` by hand:

- **local:** SSH alias / STBC user, local ports, which tiles are shown;
- **STBC:** the keys of 4.1; on save written over SSH to the user's `~/.xams/private.json`;
- **check:** folders exist and are readable, conda env present, checkouts present;
- **start / restart private apps:** starts the screens on stbc-i1 under the user's own account
  (`ops/start_private.sh`).

New users first run a one-time `ops/install_private.sh` (checkouts in their data area, environment); after that
everything goes through the tile.

### 4.3 Several users on one host

- **Ports:** fixed ports (8077, 8078) collide between users on stbc-i1. Per user a port pair, set in the settings
  (default derived from the user id).
- **Access:** an app on `127.0.0.1` of stbc-i1 is reachable by every user logged in there, which is not acceptable
  with a delete button. Each private app requires the secret token from the settings (the launcher passes it along;
  cookie after the first request); without it the app refuses every request.
- **Database:** read-only, with the user's own `~/.xams_config`; preferably a read-only Mongo user for these apps.

## 5. Order (one PR each)

1. **Private mode, Data tab:** settings file, token, run list from the folder, status current / outdated, plots and
   loadability with the user's context, greyed-out Process button, delete with keep marks and log. Tests for
   production mode unchanged.
2. **MC tab:** private MC run documents from files, MC folders from the settings.
3. **Launcher:** Settings tile, start / restart, `install_private.sh`, `start_private.sh`; per-user ports.
4. **What changed** (3.3): per data set (built, #16).
5. **Handbook:** page "Private dashboard and simulations for your own account".
6. **Process button** (3.4, private condor jobs), after 3.3.

## 6. Open points

- Settings in `~/.xams/` (home, small) or in the user's data area: plan uses the home (small file, fixed place).
- Read-only Mongo user: to be requested; until then the existing credentials of `~/.xams_config`.
