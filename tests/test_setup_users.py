"""users.yaml (names, ports, central rights), the view-only central page and the setup page of the private dashboard."""
import importlib
import json
import os
import sys

import pytest

from backend.common import users as U
from backend.private.setup import Setup, check_folder
from tests.test_dataview_production import _client, view  # noqa: F401  (fixture)
from tests.test_private import _ds, strax  # noqa: F401  (fixture)


@pytest.fixture
def usersfile(tmp_path, monkeypatch):
    f = tmp_path / "users.yaml"
    f.write_text("users:\n  acolijn: {account: z37, dashboard_port: 21235, sim_port: 8077, central_actions: true}\n"
                 "  student: {account: s99, dashboard_port: 21300, central_actions: 'yes'}\n"
                 "  odd: {account: o1, dashboard_port: 80}\n")
    monkeypatch.setenv("XAMS_DASH_USERS_FILE", str(f))
    U._CACHE.clear()
    return f


def test_repo_users_file_is_valid():
    U._CACHE.clear()
    os.environ.pop("XAMS_DASH_USERS_FILE", None)
    us = U.load()
    assert us and all(u.account for u in us.values())
    ports = [p for u in us.values() for p in (u.dashboard_port, u.sim_port) if p]
    assert len(ports) == len(set(ports))                                    # no two servers on one port


def test_users(usersfile):
    assert U.for_account("z37").name == "acolijn" and U.for_account("nobody") is None
    assert U.may_act_centrally("acolijn")
    assert not U.may_act_centrally("student")                               # only a real `true` counts
    assert not U.may_act_centrally(None) and not U.may_act_centrally("unknown")
    assert U.load()["odd"].dashboard_port is None                           # not a usable port


def test_no_file_no_rights(tmp_path, monkeypatch):
    monkeypatch.setenv("XAMS_DASH_USERS_FILE", str(tmp_path / "missing.yaml"))
    U._CACHE.clear()
    assert U.load() == {} and not U.may_act_centrally("acolijn")


def test_bad_file_no_rights(tmp_path, monkeypatch):
    f = tmp_path / "u.yaml"
    f.write_text("users: [this is: not a mapping")
    monkeypatch.setenv("XAMS_DASH_USERS_FILE", str(f))
    U._CACHE.clear()
    assert U.load() == {}


def test_private_port_from_users(usersfile, monkeypatch, tmp_path):
    from backend.private import settings as PS
    monkeypatch.setattr(U.getpass, "getuser", lambda: "s99")
    assert PS.default_port() == 21300
    monkeypatch.setattr(U.getpass, "getuser", lambda: "nobody")
    assert PS.default_port() == 20000 + os.getuid() % 20000


def test_view_only_hides_actions(view):
    c = _client(view, can_act=lambda: False)
    html = c.get("/").get_data(as_text=True)
    assert 'window.CAN_ACT = false' in html and "view only" in html
    html = _client(view, can_act=lambda: True).get("/").get_data(as_text=True)
    assert 'window.CAN_ACT = true' in html and ">view only<" not in html


def test_central_setup_page_read_only(view):
    c = _client(view)
    r = c.get("/setup")
    assert r.status_code == 200 and "Central folders" in r.get_data(as_text=True)
    assert "saveBtn" not in r.get_data(as_text=True)
    assert c.post("/api/setup/save", json={"values": {}}).status_code == 404


# ------------------------------------------------------------------------------------------------ private setup
def test_check_folder(strax, tmp_path):
    c = check_folder(str(strax), need_write=True)
    assert c["ok"] and c["n_runs"] == 2 and c["n_datasets"] == 3           # the _temp one is not a data set
    assert not check_folder("relative/path")["ok"]
    assert check_folder(str(tmp_path / "nope"))["message"] == "no such folder"
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o555)
    try:
        assert not check_folder(str(ro), need_write=True)["ok"] and check_folder(str(ro))["ok"]
    finally:
        os.chmod(ro, 0o755)


def test_setup_save(strax, tmp_path):
    s = tmp_path / "private.json"
    s.write_text(json.dumps({"strax_folder": str(strax), "token": "t" * 30, "max_jobs": 3}))
    restarts = []
    st = Setup(s, restart=lambda: restarts.append(1))
    assert [f["value"] for f in st.state()["fields"]][0] == str(strax)
    mc = tmp_path / "mc"
    mc.mkdir()
    bad = st.save({"strax_folder": str(strax), "mc_processed_folder": str(tmp_path / "nope")})
    assert not bad["saved"] and "mc_processed_folder" in bad["errors"] and not restarts
    assert st.save({"strax_folder": str(strax)})["unchanged"]
    ok = st.save({"strax_folder": str(strax), "mc_processed_folder": str(mc), "mc_raw_folder": ""})
    assert ok["saved"] and restarts == [1]
    d = json.loads(s.read_text())
    assert d["mc_processed_folder"] == str(mc) and d["token"] == "t" * 30 and d["max_jobs"] == 3   # others kept
    assert oct(os.stat(s).st_mode & 0o777) == "0o600"
    assert not st.save({"strax_folder": ""})["saved"]                        # required


def test_private_setup_routes(strax, tmp_path, monkeypatch):
    s = tmp_path / "private.json"
    s.write_text(json.dumps({"strax_folder": str(strax), "token": "secret-token", "contexts": []}))
    monkeypatch.setenv("XAMS_PRIVATE_SETTINGS", str(s))
    sys.modules.pop("v2.private_app", None)
    mod = importlib.import_module("v2.private_app")
    restarts = []
    mod._profile.setup.restart = lambda: restarts.append(1)
    c = mod.app.test_client()
    assert c.get("/setup").status_code == 403                                # the token, as everywhere
    c.get("/?token=secret-token")
    html = c.get("/setup").get_data(as_text=True)
    assert "saveBtn" in html and str(strax) in html
    j = c.post("/api/setup/check", json={"key": "strax_folder", "value": str(strax)}).get_json()
    assert j["ok"] and j["n_runs"] == 2
    assert c.post("/api/setup/check", json={"key": "token", "value": "x"}).status_code == 400
    mc = tmp_path / "mc"
    mc.mkdir()
    assert c.post("/api/setup/save", json={"values": {"strax_folder": str(strax),
                                                      "mc_raw_folder": str(mc)}}).get_json()["saved"]
    assert restarts == [1]
