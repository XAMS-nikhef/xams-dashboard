"""Deleted data sets go to <folder>/.trash first: restorable, removed for good after TRASH_DAYS."""
import time

from backend.common import folder as F
from tests.test_dataview_production import _client, view  # noqa: F401  (fixture)
from tests.test_private import _ds, strax  # noqa: F401  (fixture)


def test_delete_moves_to_trash(strax):
    res = F.delete(strax, ["007591-event_basics-aaaaaaaaaa"], confirm=True)
    assert res["deleted"] == ["007591-event_basics-aaaaaaaaaa"]
    assert not (strax / "007591-event_basics-aaaaaaaaaa").exists()
    t = F.trash_list(strax)
    assert [x["name"] for x in t] == ["007591-event_basics-aaaaaaaaaa"] and t[0]["size"] == 100
    assert "007591-event_basics-aaaaaaaaaa" not in [d.name for d in F.scan(strax)]   # not a data set any more


def test_restore(strax):
    F.delete(strax, ["007591-event_basics-aaaaaaaaaa"], confirm=True)
    e = F.trash_list(strax)[0]["entry"]
    assert F.restore(strax, e) == "007591-event_basics-aaaaaaaaaa"
    assert (strax / "007591-event_basics-aaaaaaaaaa" / "chunk-000000").exists() and F.trash_list(strax) == []


def test_restore_refuses(strax):
    F.delete(strax, ["007591-event_basics-aaaaaaaaaa"], confirm=True)
    e = F.trash_list(strax)[0]["entry"]
    _ds(strax, "007591-event_basics-aaaaaaaaaa")                      # made anew meanwhile
    for bad in ("../x", "007591-event_basics-aaaaaaaaaa", "nope__20260101-000000"):
        try:
            F.restore(strax, bad)
            assert False, bad
        except ValueError:
            pass
    try:
        F.restore(strax, e)
        assert False
    except ValueError as err:
        assert "exists again" in str(err)


def test_same_name_twice_and_empty_after_days(strax):
    now = time.time()
    p = F.to_trash(strax / "007591-event_basics-aaaaaaaaaa", now=now)
    _ds(strax, "007591-event_basics-aaaaaaaaaa")
    q = F.to_trash(strax / "007591-event_basics-aaaaaaaaaa", now=now)
    assert p != q and p.exists() and q.exists()
    assert F.empty_trash(strax, days=7, now=now + 6 * 86400) == []
    other = strax / ".trash" / "notes.txt"                             # not a trash entry: never touched
    other.write_text("x")
    assert sorted(F.empty_trash(strax, days=7, now=now + 8 * 86400)) == sorted([p.name, q.name])
    assert other.exists() and F.trash_list(strax) == []


def test_dataview_delete_trash_restore(view):
    c = _client(view)
    res = c.post("/api/delete", json={"names": ["007720-peak_positions-oldoldoldo"], "confirm": True}).get_json()
    assert res["deleted"] == ["007720-peak_positions-oldoldoldo"]
    rows = c.get("/api/trash").get_json()["rows"]
    assert [r["name"] for r in rows] == ["007720-peak_positions-oldoldoldo"]
    r = c.post("/api/trash/restore", json={"loc": rows[0]["loc"], "entry": rows[0]["entry"]}).get_json()
    assert r["restored"] == "007720-peak_positions-oldoldoldo"
    assert c.get("/api/trash").get_json()["rows"] == []
    assert c.post("/api/trash/restore", json={"loc": 99, "entry": "x"}).status_code == 400
