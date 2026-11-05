"""The run page: kind of run, which data the figures use, reference run, the page itself (no figures made here)."""
from tests.test_dataview_production import _client, _ds, view  # noqa: F401  (fixture)


def _rows(*items):
    return [{"dtype": t, "temp": False, "status": st, "mtime": m, "id": f"{t}-{st}-{m}"} for t, st, m in items]


def test_kinds(view):
    assert view.run_kinds(1, _rows(("led_calibration", "current", 1)), {}) == ["led"]
    assert view.run_kinds(1, [], {"mode": "V1725_ledcalibration_RevA"}) == ["led"]
    assert view.run_kinds(1, [], {"source": "Cs137"}) == ["event", "source"]
    assert view.run_kinds(1, [], {"source": "none"}) == ["event"]


def test_figure_dataset_prefers_current(view):
    rows = _rows(("event_info", "outdated", 5), ("event_info", "current", 1), ("event_basics", "current", 9))
    assert view.figure_dataset(rows, ["event"])["status"] == "current"
    assert view.figure_dataset(_rows(("event_basics", "current", 1)), ["event"]) is None


def test_reference_same_source(view, tmp_path):
    for run, h in ((7700, "aaaaaaaaaa"), (7710, "bbbbbbbbbb"), (7715, "cccccccccc")):
        _ds(tmp_path / "processed", f"00{run}-event_info-{h}")
    view.rundocs = lambda runs: {7700: {"source": "Cs137"}, 7710: {"source": "Na22"}, 7715: {"source": "Cs137"},
                                 7720: {"source": "Cs137"}}
    view._scan = (0.0, [])                                         # rescan with the new folders
    assert view.reference_choices(7720, ["event", "source"], {"source": "Cs137"}) == [7715, 7700]
    assert view._ref_run(7720, ["event"], {"source": "Cs137"}, "none") is None
    assert view._ref_run(7720, ["event"], {"source": "Cs137"}, "7700") == 7700


def test_page_renders(view, tmp_path):
    c = _client(view)
    c.dv.rundocs = lambda runs: {r: {"mode": "Science", "source": "none"} for r in runs}
    html = c.get("/run/7720").get_data(as_text=True)
    assert "Run 007720" in html and "window.RUN = 7720" in html and 'id="dsTable"' in html
    assert "No event data of this run" in html                    # the fixture has no event_info: no figures
    assert c.get("/run/7720/fig/rate.png").status_code == 404
    assert c.get("/run/7720/fig/nonsense.png").status_code == 404
    assert c.get("/").status_code == 200


def test_figure_dataset_prefers_the_amstrax3_event_table(view):
    """amstrax 3 `events` (with cs1) before event_info; old event windows (also called `events`) are never used."""
    rows = _rows(("event_info", "current", 1), ("events", "current", 2), ("events", "outdated", 3))
    view.is_event_table = lambda r: r["id"] == "events-current-2"
    assert view.figure_dataset(rows, ["event"])["id"] == "events-current-2"
    view.is_event_table = lambda r: False                          # only old windows: the event_info of the run
    assert view.figure_dataset(rows, ["event"])["dtype"] == "event_info"


def test_from_tables_joins_main_site_and_peaks():
    import numpy as np
    from backend.common import runfigs as R
    ev = np.zeros(3, dtype=[("time", np.int64), ("event_number", np.int64), ("cs1", np.float32), ("cs2", np.float32),
                            ("energy", np.float32)])
    ev["event_number"] = [7, 8, 9]; ev["time"] = [10, 20, 30]; ev["cs1"] = [100, 200, 300]
    sites = np.zeros(3, dtype=[(f, np.float64) for f in R.TABLE_FIELDS["sites"]])
    sites["event_number"] = [7, 7, 8]; sites["rank"] = [1, 2, 1]; sites["peak_index"] = [2, 3, 5]
    sites["drift_time"] = [21000, 30000, 5000]; sites["x"] = [1, 9, 2]; sites["y"] = [-1, 9, -2]
    peaks = np.zeros(5, dtype=[(f, np.float64) for f in R.TABLE_FIELDS["event_peaks"]])
    peaks["event_number"] = [7, 7, 7, 8, 8]; peaks["peak_index"] = [1, 2, 3, 4, 5]; peaks["type"] = [1, 2, 2, 1, 2]
    peaks["dt_s1"] = [0, 21000, 30000, np.nan, np.nan]; peaks["area"] = [1700, 9000, 500, 40, 3000]
    peaks["range_50p_area"] = [80, 900, 700, 60, 1000]
    out = R.from_tables(ev, sites, peaks)
    np.testing.assert_allclose(out["s1_area"], [1700, np.nan, np.nan])       # event 8: its S1 has no dt_s1 = 0
    np.testing.assert_allclose(out["s2_area"], [9000, 3000, np.nan])         # main site's peak; event 9: no site
    np.testing.assert_allclose(out["drift_time"], [21000, 5000, np.nan])
    np.testing.assert_allclose(out["s2_x"], [1, 2, np.nan]); np.testing.assert_allclose(out["s2_range_50p_area"], [900, 1000, np.nan])
    np.testing.assert_allclose(out["cs1"], [100, 200, 300])
