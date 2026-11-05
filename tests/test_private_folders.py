"""Private dashboards delete only in the user's own folders: not live data, not central XAMS folders, not someone
else's folder (those are shown read-only)."""
import os

from backend.common.profile import Location, Profile, private_location_problem
from tests.test_dataview_production import _ds
from v2.dataview import DataView


def test_rules(tmp_path):
    xams = tmp_path / "xams_v2"
    own = xams / "users" / "me" / "strax"
    for p in (own, xams / "xams_processed", xams / "users" / "me" / "live_mc", tmp_path / "elsewhere"):
        p.mkdir(parents=True)
    assert private_location_problem(own, xams) is None
    assert private_location_problem(tmp_path / "elsewhere", xams) is None            # own folder outside xams_v2
    assert "central" in private_location_problem(xams / "xams_processed", xams)
    assert "live data" in private_location_problem(xams / "users" / "me" / "live_mc", xams)
    assert "not your folder" in private_location_problem(own, xams, uid=os.getuid() + 1)
    (tmp_path / "link").symlink_to(xams / "xams_processed")
    assert "central" in private_location_problem(tmp_path / "link", xams)          # symlink resolved
    assert private_location_problem(tmp_path / "missing", xams) is None


def test_delete_refused_in_read_only_folder(tmp_path):
    mine, central = tmp_path / "mine", tmp_path / "central"
    _ds(mine, "007720-peak_basics-aaaaaaaaaa")
    _ds(central, "007720-peak_basics-bbbbbbbbbb")
    check = lambda p: "a central XAMS folder" if p == central else None             # noqa: E731
    v = DataView(Profile(name="private", title="p", state_dir=tmp_path / "state", providers=[],
                         locations=[Location(mine, "mine"), Location(central, "central")], location_check=check))
    pv = v.delete(["007720-peak_basics-aaaaaaaaaa", "1:007720-peak_basics-bbbbbbbbbb"])
    assert [x["name"] for x in pv["delete"]] == ["007720-peak_basics-aaaaaaaaaa"]
    assert pv["refused"][0]["reason"] == "read-only here: a central XAMS folder"
    res = v.delete(["1:007720-peak_basics-bbbbbbbbbb"], confirm=True)
    assert res["deleted"] == [] and (central / "007720-peak_basics-bbbbbbbbbb").is_dir()
    assert v.read_only() == {"central": "a central XAMS folder"}
