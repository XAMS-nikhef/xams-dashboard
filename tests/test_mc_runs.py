"""Simulated runs (xams-sim, run.runs_mc) next to data runs (runs_gas): listing, lookup by number, no SR filter."""
import mongomock

from backend.mongo_service import MongoService


def _service():
    client = mongomock.MongoClient()
    svc = MongoService.__new__(MongoService)
    svc.client = client
    svc.runs = client["run"]["runs_gas"]
    svc.runs_mc = client["run"]["runs_mc"]
    svc.processing = client["daq"]["processing"]
    svc.settings = client["daq"]["settings"]
    svc.runs.insert_one({"number": 7719, "mode": "Science_Rev2.4", "xams_bookkeeping": {"science_run_id": "SR-2026.2"}})
    svc.runs_mc.insert_one({"number": 900201, "mode": "simulation (sept)", "tags": ["simulation", "test"],
                            "xamssim": {"state": "sept", "source": "cs137_sept_standard", "n_events": 100000,
                                        "run_name": "prod_test_cs137_std"}})
    return svc


def test_is_mc():
    assert MongoService.is_mc(900201) and MongoService.is_mc("999999") and not MongoService.is_mc(7719)


def test_lists_data_and_mc_separately():
    svc = _service()
    data, n = svc.get_runs_page(default_active_sr=False)
    assert n == 1 and data[0].number == 7719 and data[0].kind == "data"
    mc, n = svc.get_runs_page(kind="mc", science_run_id="SR-2026.2")       # SR filter does not apply to MC
    assert n == 1 and mc[0].number == 900201 and mc[0].kind == "mc"
    assert mc[0].mc["state"] == "sept" and mc[0].mc["source"] == "cs137_sept_standard" and "test" in mc[0].mc["tags"]
    found, n = svc.get_runs_page(kind="mc", query_text="cs137")
    assert n == 1


def test_run_doc_from_the_right_collection():
    svc = _service()
    assert svc.get_run_doc(900201)["xamssim"]["state"] == "sept"
    assert svc.get_run_doc(7719)["mode"] == "Science_Rev2.4"
    svc.append_processing_history(900201, {"action": "test"})
    assert svc.runs_mc.find_one({"number": 900201})["processing_history"][0]["action"] == "test"
    assert "processing_history" not in svc.runs.find_one({"number": 7719})
