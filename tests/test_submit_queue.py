from backend.submit_queue import SubmitQueue


def test_queue_add_dedup_remove(tmp_path):
    q = SubmitQueue(str(tmp_path / "q.json"))
    assert q.add({"run_id": 1, "targets": ["event_info"]})
    assert not q.add({"run_id": 1, "targets": ["event_info"]})
    assert q.add({"run_id": 2, "targets": ["event_info"]})
    assert q.queued_run_ids() == {1, 2}
    assert q.remove(1) == 1
    assert q.queued_run_ids() == {2}
    assert q.remove() == 1
    assert q.items() == []


def test_process_once_stops_at_busy(tmp_path):
    q = SubmitQueue(str(tmp_path / "q.json"))
    for r in (1, 2, 3):
        q.add({"run_id": r})
    calls = []

    def submit(req):
        calls.append(req["run_id"])
        return {"status": "submitted"} if req["run_id"] == 1 else {"status": "busy", "reason": "5/5"}

    q.process_once(submit)
    assert calls == [1, 2]
    items = q.items()
    assert [x["run_id"] for x in items] == [2, 3]
    assert items[0]["attempts"] == 1


def test_failed_run_leaves_queue(tmp_path):
    q = SubmitQueue(str(tmp_path / "q.json"))
    q.add({"run_id": 7})
    q.process_once(lambda req: {"status": "failed"})
    assert q.items() == []
