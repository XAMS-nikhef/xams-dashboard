"""Current corrections versions and the submit default from the run database (daq.settings, 2026-11-27), with the
environment as fallback. No database needed."""
import types

from backend.common import profile as P


def coll(docs=None, fail=False):
    def find_one(q):
        if fail:
            raise RuntimeError("no database")
        return (docs or {}).get(q["name"])
    return types.SimpleNamespace(find_one=find_one)


def setup_function():
    P._settings_cache.clear()


def test_current_versions_from_settings(monkeypatch):
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD5,v4")
    c = coll({"current_corrections_versions": {"name": "current_corrections_versions", "value": ["PROD6", " ONLINE"]}})
    assert P.current_versions(c) == ["PROD6", "ONLINE"]


def test_current_versions_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("XAMS_DASH_CURRENT_VERSIONS", "PROD5,v4")
    assert P.current_versions(coll()) == ["PROD5", "v4"]
    assert P.current_versions(coll(fail=True)) == ["PROD5", "v4"]


def test_unreadable_database_keeps_last_value():
    ok = coll({"x": {"name": "x", "value": "A"}})
    assert P.db_setting("x", ok, now=0) == "A"
    assert P.db_setting("x", coll(fail=True), now=1000) == "A"


def test_cache_without_explicit_collection(monkeypatch):
    P._settings_cache["y"] = (0.0, "cached")
    monkeypatch.setattr(P.time, "monotonic", lambda: 10.0)
    assert P.db_setting("y") == "cached"


def test_submit_default(monkeypatch):
    c = coll({"online_corrections_version": {"name": "online_corrections_version", "value": "ONLINE2"}})
    monkeypatch.setenv("XAMS_AUTOPROC_CORRECTIONS", "PROD6")
    assert P.submit_default_version(c) == "PROD6"
    monkeypatch.setenv("XAMS_AUTOPROC_CORRECTIONS", "db")
    assert P.submit_default_version(c) == "ONLINE2"
    P._settings_cache.clear()
    monkeypatch.delenv("XAMS_AUTOPROC_CORRECTIONS")
    assert P.submit_default_version(coll()) == "ONLINE"
