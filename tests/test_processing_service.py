from backend.processing_service import ProcessingService


def test_submit_run_failure_when_command_missing(tmp_path):
    svc = ProcessingService(
        amstrax_dir=str(tmp_path / "missing"),
        log_dir=str(tmp_path / "logs"),
        output_dir=str(tmp_path / "out"),
    )
    out = svc.submit_run(1234, target="events")
    assert out["submitted"] is False
    assert out["returncode"] != 0


def test_parse_submit_output_submitted():
    from backend.processing_service import parse_submit_output
    out = parse_submit_output(0, "INFO:job_submission:Job process_007719_online submitted successfully.\n")
    assert out["status"] == "submitted"
    assert out["job_name"] == "process_007719_online"


def test_parse_submit_output_busy_exit_zero():
    from backend.processing_service import parse_submit_output
    out = parse_submit_output(0, "INFO:__main__:Found 5 running jobs.\nINFO:__main__:Too many jobs running (5/5).\n")
    assert out["status"] == "busy"
    assert "5/5" in out["reason"]


def test_parse_submit_output_dry_and_errors():
    from backend.processing_service import parse_submit_output
    assert parse_submit_output(0, "Would have submitted job for run 007719")["status"] == "dry_run"
    assert parse_submit_output(0, "ERROR: Error submitting job: boom")["status"] == "failed"
    assert parse_submit_output(0, "nothing useful")["status"] == "failed"
    assert parse_submit_output(1, "Traceback\nKeyError: x")["reason"] == "KeyError: x"


def test_submit_run_disabled(tmp_path):
    svc = ProcessingService(amstrax_dir=str(tmp_path), log_dir=str(tmp_path / "logs"),
                            output_dir=str(tmp_path / "out"), submit_mode="off")
    out = svc.submit_run(1234, target="events")
    assert out["submitted"] is False
    assert out["status"] == "disabled"


def test_submit_run_passes_max_jobs_and_mode(tmp_path, monkeypatch):
    import subprocess
    seen = {}

    class P:
        returncode = 0
        stdout = ""
        stderr = "Would have submitted job for run 001234"

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    svc = ProcessingService(amstrax_dir=str(tmp_path), log_dir=str(tmp_path / "logs"),
                            output_dir=str(tmp_path / "out"), submit_mode="dry", max_jobs=25)
    out = svc.submit_run(1234, target=["event_info"], corrections_version=None)
    assert out["status"] == "dry_run"
    assert "--production" not in seen["cmd"]
    i = seen["cmd"].index("--max_jobs")
    assert seen["cmd"][i + 1] == "25"
