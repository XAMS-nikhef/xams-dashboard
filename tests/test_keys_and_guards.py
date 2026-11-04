"""Keys for the production actions and the deletion guards (no current version, bulk limit)."""
import os

import pytest

from backend.common import keys as K
from tests.test_dataview_production import _ds, view  # noqa: F401  (fixture)


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    f = tmp_path / "keys.json"
    monkeypatch.setenv("XAMS_DASH_KEYS_FILE", str(f))
    K._CACHE.clear()
    return f


def test_no_file_refuses_everything(keyfile):
    assert K.load() == {} and K.user_for("anything") is None and K.user_for("") is None


def test_add_check_remove(keyfile):
    key = K.add("acolijn")
    assert oct(os.stat(keyfile).st_mode & 0o777) == "0o600"
    assert K.user_for(key) == "acolijn" and K.user_for(key + "x") is None
    K.remove("acolijn")
    assert K.user_for(key) is None


def test_file_readable_by_others_is_not_trusted(keyfile):
    key = K.add("acolijn")
    os.chmod(keyfile, 0o644)
    K._CACHE.clear()
    assert K.user_for(key) is None


def test_outdated_without_current_version_refused(view):
    view.p.require_current = True
    # event_basics of 7720: only an outdated (kept) data set; unkeep it so only the new rule can refuse it
    from backend.common import folder as F
    F.set_keep(view.p.state_dir, "007720-event_basics-keptkeptke", False)
    pv = view.delete(["007720-event_basics-keptkeptke", "007720-peak_positions-oldoldoldo"])
    assert [x["name"] for x in pv["delete"]] == ["007720-peak_positions-oldoldoldo"]   # a current one exists
    assert "no current version" in pv["refused"][0]["reason"]


def test_bulk_limit(view):
    view.p.bulk_limit = 0.05                                # one of three non-raw data sets is 33 %
    pv = view.delete(["007720-peak_positions-oldoldoldo"])
    assert pv["large"]["fraction_datasets"] > 0.05
    res = view.delete(["007720-peak_positions-oldoldoldo"], confirm=True)
    assert res["deleted"] == [] and "Nothing deleted" in res["errors"][0]["error"]
    res = view.delete(["007720-peak_positions-oldoldoldo"], confirm=True, allow_large=True)
    assert res["deleted"] == ["007720-peak_positions-oldoldoldo"]
