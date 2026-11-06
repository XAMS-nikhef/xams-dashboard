# XAMS Dashboard

Flask-based run browser and processing trigger UI for XAMS on STBC.

## Features
- Browse runs with status filters
- Inspect run metadata and data products (type/host/location/lineage)
- Check loadability with current local amstrax/strax context
- Submit HTCondor processing jobs to `events` target
- Plot event-level summaries (drift time, S1/S2, XY)

## Quick start (local)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m v2.app
```

Open: http://127.0.0.1:8070

## Environment variables
- `XAMS_MONGO_URI` (default: `mongodb://user:password@127.0.0.1:27017/admin`)
- `XAMS_RUN_DB` (default: `run`)
- `XAMS_RUN_COLLECTION` (default: `runs_gas`)
- `XAMS_PROCESSING_DB` (default: `daq`)
- `XAMS_PROCESSING_COLLECTION` (default: `processing`)
- `XAMS_STBC_AMSTRAX_DIR` (default: `/data/xenon/xams_v2/software/amstrax/amstrax/auto_processing_new`)
- `XAMS_STBC_LOG_DIR` (default: `/data/xenon/xams_v2/logs`)
- `XAMS_STBC_OUTPUT_DIR` (default: `/data/xenon/xams_v2/xams_processed`)
- `XAMS_DASH_HOST` (default: `127.0.0.1`)
- `XAMS_DASH_PORT` (default: `8070`)

## STBC ops
Use scripts in `ops/`:
- `start_dashboard.sh`
- `stop_dashboard.sh`
- `restart_dashboard.sh`
- `status_dashboard.sh`
- `start_autoprocess_online.sh`

Default dashboard URL on STBC (with tunnel):
- `http://127.0.0.1:18070`

Notes:
- `run_id` is optional and can be added as query parameter when needed.
- Legacy `/v2` routes are kept as compatibility redirects.

## Private dashboard (your own processed data)

A second, separate app for the processed data in **your own** strax folder (plan: `docs/PRIVATE_MODE_PLAN.md`):
runs from the folder, status per data set (current / outdated / unknown / incomplete) from your own analysis
contexts, plots of any stored version, keep marks and deletion (preview, confirm, log). The production dashboard
(`v2/app.py`) does not use any of it.

1. Your own checkout (not the production one), e.g. in your data area:
   `git clone https://github.com/XAMS-nikhef/xams-dashboard.git`
2. Settings `~/.xams/private.json` (format in `backend/private/settings.py`): `strax_folder` and your context
   providers (`contexts`: a function of your analysis code that returns the context of a run, e.g.
   `xams_sr.py:context_for_runs(["{run}"])`; optionally limited to a run range).
3. `ops/start_private.sh` (start | stop | status | url). The first start adds a secret token to the settings; every
   request needs it (`?token=` once, then a cookie). Port: `dashboard_port` of the settings, else your entry in
   `users.yaml`, else 20000 + uid % 20000.
4. From your machine: `ssh -N -L 18078:127.0.0.1:<port> stbc-i1`, then `http://127.0.0.1:18078/?token=<token>`.

Setup (gear icon, `/setup`): your folders for data and MC, each with a **Check** (exists, readable, writable,
how many runs); **Save and restart** writes them into `~/.xams/private.json` (other keys kept) and the app
restarts with them. The central page shows its folders there, not changeable.

## Users (`users.yaml`)

Names, STBC accounts, the ports of each user's private servers and `central_actions` (may submit / delete on the
central dashboard; default view only). No secrets: keys stay in the accounts' homes. Central actions need both a
key in xamsdata's `~/.xams_dashboard_keys.json` (`python -m backend.common.keys add <name>`) and
`central_actions: true`; without them the central pages are view only (no action buttons; the server refuses
the actions too). A new user: a block with the next free ports, PR, deploy.

Files it keeps in the strax folder: `.dashboard_lineage.json` (hash cache), `.dashboard_keep.json` (keep marks),
`.dashboard_deletions.log`, `.dashboard_private.log` (app log, only readable by you). Deletion is limited to data-set
folders (`<run>-<type>-<hash>`) directly inside the strax folder; kept ones are never deleted.

**Trash:** a deleted data set is first moved to `.trash/` in its own folder (a rename, nothing copied), shown in the
**Trash** panel of the run list with a **restore** button, and removed for good after 7 days
(`XAMS_DASH_TRASH_DAYS`); the disk space comes free only then. Same for the central page and the old page's
"Delete data". A restored central data set gets no `data[]` entry back in the run document.
