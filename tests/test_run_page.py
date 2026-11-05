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
