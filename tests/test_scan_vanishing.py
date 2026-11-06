"""A data set folder that disappears during the scan (strax renames *_temp when done) must not drop the location."""
from backend.common import folder as F


def test_scan_skips_vanished_folder(tmp_path, monkeypatch):
    for name in ("007762-raw_records-y5oixg6qla", "007762-events-gqwd5zo6ys", "007762-sites-newdgk36bv_temp"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "chunk").write_bytes(b"x" * 10)
    real = F._size

    def flaky(path):
        if path.name.endswith("_temp"):
            raise FileNotFoundError(path)                 # renamed by strax between listing and sizing
        return real(path)

    monkeypatch.setattr(F, "_size", flaky)
    got = {d.dtype for d in F.scan(tmp_path)}
    assert got == {"raw_records", "events"}
