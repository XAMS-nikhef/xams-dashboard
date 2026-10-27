"""Make data types of one run with a context provider (the private dashboard's Process; run as a condor job in the
provider's python, no dashboard imports beyond lineage_worker next to it).

    python make_worker.py <request.json>
    request: {"provider": {...}, "run": "007720", "targets": ["peak_positions", "event_basics"]}

The provider is the one that judges the run in the dashboard (lineage_worker._factory), so what is made here is
"current" there. strax reuses every current data type of the chain and stores the targets in the provider's
output folder.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lineage_worker import _factory  # noqa: E402


def main():
    req = json.load(open(sys.argv[1]))
    run = req["run"]
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} run {run}, provider {req['provider'].get('name')}, "
          f"targets {req['targets']}", flush=True)
    st = _factory(req["provider"])(run)
    for t in req["targets"]:
        t0 = time.time()
        print(f"making {t} ...", flush=True)
        st.make(run, t, progress_bar=False)
        print(f"  {t}: done in {time.time() - t0:.0f} s, key {st.key_for(run, t).lineage_hash}", flush=True)
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} all done", flush=True)


if __name__ == "__main__":
    main()
