"""Central contexts that need a run (used as providers by the production profile, in the lineage worker's process).

    mc(run)   a simulated run (xams-sim): corrections MC2 with the run's own values from its run document (amstrax
              for_mc_run, "latest" reconstruction) — as backend/loadability.py. Default: the production MC folders;
              the private dashboard passes its own (private.json provider, e.g.
              "args": ["{run}", "<XAMSSIM_AMSTRAX_STORE>", "<strax_folder>"]).
"""
MC_RAW, MC_PROCESSED = "/data/xenon/xams_v2/mc_raw_records", "/data/xenon/xams_v2/mc_processed"
MC_CORRECTIONS = "MC2"


def mc(run, raw=MC_RAW, processed=MC_PROCESSED, corrections_version=MC_CORRECTIONS):
    import amstrax
    import strax
    st = amstrax.contexts.xams(output_folder=processed, corrections_version=corrections_version)
    st.storage = [strax.DataDirectory(raw, readonly=True, provide_run_metadata=True),
                  strax.DataDirectory(processed, readonly=True)] + st.storage
    if raw not in amstrax.xams_config.RUNDOC_DIRS:
        amstrax.xams_config.RUNDOC_DIRS.append(raw)
    return amstrax.contexts.for_mc_run(st, f"{int(run):06d}", use="latest")
