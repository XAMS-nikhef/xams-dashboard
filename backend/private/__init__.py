"""Private mode of the dashboard (docs/PRIVATE_MODE_PLAN.md): a dashboard for the processed data in a user's own
strax folder, run by that user (v2/private_app.py). Nothing here is used by the production dashboard (v2/app.py).

    settings  the user's settings file (~/.xams/private.json)
    folder    the strax folder: data sets, sizes, keep marks, deletion (only inside the folder) and its log
    lineage   which data sets are current: hashes from the user's context providers (one subprocess per provider)
    stored    reading a stored data set directly from its folder (plots of any version, no context needed)
"""
