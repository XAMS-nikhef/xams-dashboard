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


def test_shared_folders_read_only(tmp_path):
    """Other users' folders (shared_folders): listed, always read-only here, even when this account could write."""
    from types import SimpleNamespace

    from backend.common.profile import SHARED, private_profile
    mine, other = tmp_path / "mine", tmp_path / "other"
    _ds(mine, "007720-peak_basics-aaaaaaaaaa")
    _ds(other, "007721-peak_basics-bbbbbbbbbb")
    s = SimpleNamespace(strax_folder=mine, contexts=[], token="t", shared_folders=[other, other])
    p = private_profile(s)
    labels = [x.label for x in p.locations]
    assert labels[0] == "strax_data" and labels[1].startswith("shared: ") and labels[2] == labels[1] + "'"
    assert p.location_check(mine) is None and p.location_check(other) == SHARED
    assert p.state_dir == mine                                                       # state never in a shared folder
    v = DataView(p)
    res = v.delete(["1:007721-peak_basics-bbbbbbbbbb"], confirm=True)
    assert res["deleted"] == [] and (other / "007721-peak_basics-bbbbbbbbbb").is_dir()


def test_shared_folders_setup(tmp_path):
    import json

    from backend.private.settings import PrivateSettings
    from backend.private.setup import Setup
    mine, a, b = tmp_path / "mine", tmp_path / "a", tmp_path / "b"
    for d in (mine, a, b):
        d.mkdir()
    os.chmod(b, 0o555)                                                               # readable, not writable: fine
    try:
        f = tmp_path / "private.json"
        f.write_text(json.dumps({"strax_folder": str(mine)}))
        st = Setup(f, restart=lambda: None)
        assert st.check("shared_folders", f"{a}; {b}")["ok"]
        assert not st.check("shared_folders", f"{a};{tmp_path / 'nope'}")["ok"]
        assert st.save({"strax_folder": str(mine), "shared_folders": f" {a} ;{b}; "})["saved"]
        assert json.loads(f.read_text())["shared_folders"] == [str(a), str(b)]       # stored as a list
        assert next(x for x in st.state()["fields"] if x["key"] == "shared_folders")["value"] == f"{a}; {b}"
        assert st.save({"strax_folder": str(mine), "shared_folders": f"{a};{b}"})["unchanged"]
        assert PrivateSettings.load(f).shared_folders == [a, b]
    finally:
        os.chmod(b, 0o755)
