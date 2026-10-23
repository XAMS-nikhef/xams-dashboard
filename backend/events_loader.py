from __future__ import annotations

import time
import math
from typing import Any, Dict, Tuple

_CACHE = {}  # type: Dict[Any, Tuple[float, Dict[str, Any]]]
_CACHE_TTL = 60
PROCESSED = "/data/xenon/xams_v2/xams_processed"
MC_RAW, MC_PROCESSED = "/data/xenon/xams_v2/mc_raw_records", "/data/xenon/xams_v2/mc_processed"
MC_RUNS = (900000, 999999)
MC_CORRECTIONS = "MC1"


def _versions(doc: Dict[str, Any]) -> list:
    """Corrections versions with which event_info of the run is stored (data[] entries), newest first; 'online' =
    stored without a version (the online / default context)."""
    import re
    found = []
    for d in doc.get("data", []) or []:
        if isinstance(d, dict) and d.get("type") == "event_info":
            v = str(d.get("corrections_version") or "online")
            if v not in found:
                found.append(v)

    def key(v):
        m = re.match(r"^v(\d+)$", v)
        return (2, int(m.group(1))) if m else ((0, 0) if v == "online" else (1, 0))
    return sorted(found, key=key, reverse=True)


def _event_context(amstrax, run_id: int, version):
    """The amstrax context in which a run's stored event data are found: data runs with their corrections version
    (None = online / default), simulated runs from the MC folders with their MC corrections (run document)."""
    rid = "{:06d}".format(run_id)
    if MC_RUNS[0] <= run_id <= MC_RUNS[1]:
        import strax
        st = amstrax.contexts.xams(output_folder=MC_PROCESSED, corrections_version=MC_CORRECTIONS)
        st.storage = [strax.DataDirectory(MC_RAW, readonly=True, provide_run_metadata=True),
                      strax.DataDirectory(MC_PROCESSED, readonly=True)] + st.storage
        if MC_RAW not in amstrax.xams_config.RUNDOC_DIRS:
            amstrax.xams_config.RUNDOC_DIRS.append(MC_RAW)
        return amstrax.contexts.for_mc_run(st, rid)
    kw = {} if version in (None, "online") else {"corrections_version": version}
    return amstrax.contexts.xams(output_folder=PROCESSED, **kw)


def _to_list(arr, names, field):
    if field in names:
        return arr[field].tolist()
    return []


def _finite(values):
    out = []
    for v in values:
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isfinite(fv):
            out.append(fv)
    return out


def _paired_finite(a, b):
    aa = []
    bb = []
    for x, y in zip(a, b):
        try:
            fx = float(x)
            fy = float(y)
        except Exception:
            continue
        if math.isfinite(fx) and math.isfinite(fy):
            aa.append(fx)
            bb.append(fy)
    return aa, bb


def _is_led_run_doc(doc: Dict[str, Any]) -> bool:
    if not isinstance(doc, dict):
        return False
    mode = str(doc.get("mode") or "").lower()
    xbk = doc.get("xams_bookkeeping") if isinstance(doc.get("xams_bookkeeping"), dict) else {}
    run_class = str(xbk.get("run_class") or "").lower()
    if run_class == "led":
        return True
    if "led" in mode:
        return True
    tags = doc.get("tags") or []
    for t in tags:
        name = (t.get("name") if isinstance(t, dict) else str(t)).lower()
        if "led" in name:
            return True
    return False


def load_event_features(
    run_id: int,
    max_points: int = 120000,
    max_peaks: int = 120000,
    max_waveforms: int = 40,
    corrections: str | None = None,
) -> Dict[str, Any]:
    now = time.time()
    run_id = int(run_id)
    cache_key = (run_id, corrections)

    if cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if now - ts < _CACHE_TTL:
            return payload

    payload = {
        "ok": False,
        "plot_mode": "event",
        "is_led_run": False,
        "drift_time": [],
        "s1_area": [],
        "s2_area": [],
        "x": [],
        "y": [],
        "source": [],
        "peak_source": "",
        "peak_area": [],
        "peak_aft": [],
        "peak_width_50": [],
        "peak_area_width": [],
        "peak_type": [],
        "waveforms": [],
        "led_channel": [],
        "led_area": [],
        "led_amplitude_led": [],
        "led_amplitude_noise": [],
        "led_amplitude_diff": [],
        "reason": "",
        "corrections_version": None,
        "corrections_versions": [],
    }

    try:
        import amstrax  # type: ignore

        rid = "{:06d}".format(run_id)
        run_doc = amstrax.get_run_collection(run_id).find_one(        # runs_mc for simulated runs, else runs_gas
            {"number": run_id}, {"mode": 1, "xams_bookkeeping": 1, "tags": 1, "data": 1, "_id": 0}) or {}
        is_led = _is_led_run_doc(run_doc)
        payload["is_led_run"] = bool(is_led)

        if is_led:
            st_led = amstrax.contexts.xams_led(output_folder="/data/xenon/xams_v2/xams_processed")
            if st_led.is_stored(rid, "led_calibration"):
                led = st_led.get_array(rid, "led_calibration", progress_bar=False)
                if len(led):
                    led = led[: min(len(led), max_points)]
                    names = set(led.dtype.names)
                    area = _finite(_to_list(led, names, "area"))
                    amp_led = _finite(_to_list(led, names, "amplitude_led"))
                    amp_noise = _finite(_to_list(led, names, "amplitude_noise"))
                    ch = []
                    if "channel" in names:
                        ch = [int(c) for c in led["channel"].tolist()[: len(area)]]

                    # align LED/noise arrays
                    amp_led, amp_noise = _paired_finite(amp_led, amp_noise)
                    n = min(len(amp_led), len(amp_noise))
                    amp_diff = [amp_led[i] - amp_noise[i] for i in range(n)]

                    payload.update(
                        {
                            "ok": bool(area or amp_led or ch),
                            "plot_mode": "led",
                            "source": ["led_calibration"],
                            "led_channel": ch,
                            "led_area": area,
                            "led_amplitude_led": amp_led,
                            "led_amplitude_noise": amp_noise,
                            "led_amplitude_diff": amp_diff,
                            "reason": "ok from led_calibration",
                        }
                    )
                else:
                    payload["plot_mode"] = "led"
                    payload["reason"] = "led_calibration exists but empty"
            else:
                payload["plot_mode"] = "led"
                payload["reason"] = "no led_calibration stored in current LED context"

            # Optional waveform sampling from records_led.
            try:
                if st_led.is_stored(rid, "records_led"):
                    rled = st_led.get_array(rid, "records_led", progress_bar=False)
                    if len(rled):
                        rled = rled[: min(len(rled), max_waveforms)]
                        wfs = []
                        for rec in rled:
                            raw = rec["data"].tolist()
                            step = max(1, int(len(raw) / 500))
                            data = raw[::step]
                            dt = int(rec["dt"])
                            ts = [j * dt * step for j in range(len(data))]
                            wfs.append({"area": float(sum(data)), "t_ns": ts, "amp": [float(v) for v in data]})
                        payload["waveforms"] = wfs
            except Exception:
                pass

            _CACHE[cache_key] = (now, payload)
            return payload

        # the context of the run's stored event data: the requested corrections version, else the newest stored one
        versions = _versions(run_doc)
        payload["corrections_versions"] = versions
        tried = [corrections] if corrections else (versions or ["online"])
        st, chosen = None, None
        for v in tried:
            st_v = _event_context(amstrax, run_id, v)
            if st_v.is_stored(rid, "event_info") or st_v.is_stored(rid, "event_basics"):
                st, chosen = st_v, v
                break
        if st is None:
            st, chosen = _event_context(amstrax, run_id, tried[0]), tried[0]
        payload["corrections_version"] = chosen

        data = {}
        for t in ("event_info", "event_basics", "event_positions", "events"):
            if st.is_stored(rid, t):
                arr = st.get_array(rid, t, progress_bar=False)
                if len(arr):
                    data[t] = arr[: min(len(arr), max_points)]

        if not data:
            payload["reason"] = "no event-level data stored in current context"
        else:
            source = list(data.keys())

            # Drift time: prefer explicit field, else derive from events timing
            drift = []
            for t in ("event_info", "event_basics", "events"):
                arr = data.get(t)
                if arr is None:
                    continue
                names = set(arr.dtype.names)
                if "drift_time" in names:                       # (not endtime - time: that is the event window)
                    drift = arr["drift_time"].tolist()
                    break

            # S1/S2: event_info or event_basics
            s1 = []
            s2 = []
            for t in ("event_info", "event_basics"):
                arr = data.get(t)
                if arr is None:
                    continue
                names = set(arr.dtype.names)
                s1 = _to_list(arr, names, "s1_area") or _to_list(arr, names, "s1") or _to_list(arr, names, "cs1")
                s2 = _to_list(arr, names, "s2_area") or _to_list(arr, names, "s2") or _to_list(arr, names, "cs2")
                if s1 and s2:
                    break

            # XY: event_positions first, else info/basics if present
            x = []
            y = []
            for t in ("event_positions", "event_info", "event_basics"):
                arr = data.get(t)
                if arr is None:
                    continue
                names = set(arr.dtype.names)
                x = _to_list(arr, names, "x")
                y = _to_list(arr, names, "y")
                if x and y:
                    break

            drift = _finite(drift)
            s1, s2 = _paired_finite(s1, s2)
            x, y = _paired_finite(x, y)

            payload.update(
                {
                    "ok": bool(drift or (s1 and s2) or (x and y)),
                    "drift_time": drift,
                    "s1_area": s1,
                    "s2_area": s2,
                    "x": x,
                    "y": y,
                    "source": source,
                }
            )

            missing = []
            if not drift:
                missing.append("drift_time")
            if not (s1 and s2):
                missing.append("S1/S2")
            if not (x and y):
                missing.append("XY")

            payload["reason"] = "ok from {} (corrections {}){}".format(
                ",".join(source), chosen,
                ("; missing " + ", ".join(missing)) if missing else "",
            )

        # Peak basics quick-check fields
        rid = "{:06d}".format(run_id)
        if st.is_stored(rid, "peak_basics"):
            pb = st.get_array(rid, "peak_basics", progress_bar=False)
            if len(pb):
                pb = pb[: min(len(pb), max_peaks)]
                names = set(pb.dtype.names)
                area = _to_list(pb, names, "area")
                aft = _to_list(pb, names, "area_fraction_top")
                width = _to_list(pb, names, "range_50p_area") or _to_list(pb, names, "rise_time")
                ptype = _to_list(pb, names, "type")
                area, aft = _paired_finite(area, aft)
                area2, width = _paired_finite(_to_list(pb, names, "area"), width)
                # keep one type list finite and same length as area/aft pair when possible
                ptype = [int(t) for t in ptype[: len(area)] if isinstance(t, (int, float))]
                payload.update(
                    {
                        "peak_source": "peak_basics",
                        "peak_area": area,
                        "peak_aft": aft,
                        "peak_width_50": width,
                        "peak_area_width": area2,
                        "peak_type": ptype,
                    }
                )

                # Optional tiny waveform sample from first second
                try:
                    if st.is_stored(rid, "peaks") and "time" in names:
                        t0 = int(pb["time"][0])
                        t1 = t0 + int(1e9)
                        p = st.get_array(rid, "peaks", time_range=(t0, t1), progress_bar=False)
                        wfs = []
                        if len(p):
                            # pick top peaks and keep payload manageable
                            order = sorted(range(len(p)), key=lambda i: float(p["area"][i]), reverse=True)[:max_waveforms]
                            for idx in order:
                                pi = p[idx]
                                raw = pi["data"][: int(pi["length"])].tolist()
                                # decimate to avoid huge frontend payload
                                step = max(1, int(len(raw) / 500))
                                data = raw[::step]
                                dt = int(pi["dt"])
                                ts = [j * dt * step for j in range(len(data))]
                                wfs.append({"area": float(pi["area"]), "t_ns": ts, "amp": [float(v) for v in data]})
                        payload["waveforms"] = wfs
                except Exception:
                    pass

    except Exception as e:
        payload["reason"] = "{}".format(e)

    _CACHE[cache_key] = (now, payload)
    return payload
