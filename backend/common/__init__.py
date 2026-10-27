"""Shared core of the data view (docs/UNIFIED_DASHBOARD_REPORT.md): used by the private dashboard (v2/private_app.py)
and by the production page /v3 (v2/app.py), each with its own profile (profile.py).

    profile   what differs: run source, folders, providers, deletion policy, state files, token
    folder    data sets in a folder, sizes, keep marks, deletion (only inside the profile's folders) and its log
    lineage   which data sets are current: hashes from the profile's context providers (one subprocess each)
    whatchanged  why a data set is outdated (stored vs current lineage)
    stored    reading a stored data set directly from its folder
"""
