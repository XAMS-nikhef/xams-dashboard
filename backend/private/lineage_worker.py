"""Lineage hashes of one context provider, in its own process (run with the provider's python; no dashboard imports).

stdin:  {"provider": {...}, "items": [["007591", ["event_basics", "peaks"]], ...], "want": "hash" | "lineage"}
stdout: one JSON line: {"hashes": {"007591": {"event_basics": "hce5zq2ven", "peaks": null}}, "errors": {"007592": "..."}}
        with "want": "lineage" the full current lineage instead of the hash ({data type: [plugin, version, options]})

Providers (settings "contexts"):
    {"kind": "function", "path": ".../lib/xams_sr.py", "call": "context_for_runs", "args": [["{run}"]]}
        the function of a file (its folder on sys.path, so its own imports work); "{run}" in args = the run id
    {"kind": "amstrax", "context": "xams", "kwargs": {...}, "config": {...}}
        amstrax.contexts.<context>(**kwargs) with set_config(config)
    "runs": [first, last]   (optional) the provider only judges these runs; for others every hash is null
        (e.g. a context for simulated runs, which would otherwise also claim every data run)
A hash is null when the provider cannot make that data type for that run (unknown run, unknown data type).
Analyses with modules of the same name (two xams_sr.py) can be providers side by side: one process each.
"""
import importlib.util
import json
import os
import sys
import warnings


def _subst(v, run):
    if isinstance(v, str):
        return v.replace("{run}", run)
    if isinstance(v, list):
        return [_subst(x, run) for x in v]
    if isinstance(v, dict):
        return {k: _subst(x, run) for k, x in v.items()}
    return v


def _factory(p):
    if p.get("kind", "function") == "amstrax":
        import amstrax

        def make(run):
            st = getattr(amstrax.contexts, p.get("context", "xams"))(**_subst(p.get("kwargs") or {}, run))
            if p.get("config"):
                st.set_config(_subst(p["config"], run))
            return st
        return make
    path = os.path.abspath(p["path"])
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(path))[0], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    fn = getattr(mod, p.get("call", "context"))
    return lambda run: fn(*_subst(p.get("args") or [], run), **_subst(p.get("kwargs") or {}, run))


def main():
    warnings.filterwarnings("ignore")
    req = json.loads(sys.stdin.read())
    out = {"hashes": {}, "errors": {}}
    real_stdout = sys.stdout
    sys.stdout = sys.stderr                                  # chatty imports must not spoil the JSON line
    try:
        make = _factory(req["provider"])
        lo, hi = req["provider"].get("runs") or (None, None)
        for run, dtypes in req["items"]:
            h = out["hashes"].setdefault(run, {})
            if lo is not None and not (int(lo) <= int(run) <= int(hi)):
                h.update({t: None for t in dtypes})
                continue
            try:
                st = make(run)
            except Exception as e:                           # noqa: BLE001 (run unknown to this provider)
                out["errors"][run] = f"{type(e).__name__}: {e}"[:300]
                for t in dtypes:
                    h[t] = None
                continue
            for t in dtypes:
                try:
                    key = st.key_for(run, t)
                    h[t] = key.lineage if req.get("want") == "lineage" else key.lineage_hash
                except Exception:                            # noqa: BLE001 (data type unknown to this context)
                    h[t] = None
    except Exception as e:                                   # noqa: BLE001
        out["fatal"] = f"{type(e).__name__}: {e}"[:500]
    sys.stdout = real_stdout
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
