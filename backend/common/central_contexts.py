"""Central contexts that need a run (used as providers by the production profile, in the lineage worker's process).

    mc(run)   a simulated run (xams-sim production): MC folders, corrections MC1 with the run's own values from its run
              document (amstrax for_mc_run, "latest" reconstruction) — as backend/loadability.py
"""
MC_RAW, MC_PROCESSED = "/data/xenon/xams_v2/mc_raw_records", "/data/xenon/xams_v2/mc_processed"


def mc(run):
    import amstrax
    import strax
    st = amstrax.contexts.xams(output_folder=MC_PROCESSED, corrections_version="MC1")
    st.storage = [strax.DataDirectory(MC_RAW, readonly=True, provide_run_metadata=True),
                  strax.DataDirectory(MC_PROCESSED, readonly=True)] + st.storage
    if MC_RAW not in amstrax.xams_config.RUNDOC_DIRS:
        amstrax.xams_config.RUNDOC_DIRS.append(MC_RAW)
    return amstrax.contexts.for_mc_run(st, f"{int(run):06d}", use="latest")
