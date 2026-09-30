import configparser
from dataclasses import dataclass
import os
from typing import Dict


def _load_xams_config() -> Dict[str, str]:
    path = os.getenv("XAMS_CONFIG_FILE", os.path.join(os.path.expanduser("~"), ".xams_config"))
    if not os.path.exists(path):
        return {}
    cp = configparser.ConfigParser()
    cp.read(path)
    if "default" not in cp:
        return {}
    return {k.upper(): v for k, v in cp["default"].items()}


_XAMS = _load_xams_config()


def _cfg_env(name: str, fallback: str) -> str:
    return os.getenv(name, _XAMS.get(name, fallback))


@dataclass(frozen=True)
class Settings:
    mongo_uri: str = _cfg_env(
        "XAMS_MONGO_URI",
        "mongodb://{}:{}@127.0.0.1:{}/admin".format(
            _XAMS.get("MONGO_USER", "user"),
            _XAMS.get("MONGO_PASSWORD", "password"),
            _XAMS.get("MONGO_PORT", "27017"),
        ),
    )
    run_db: str = os.getenv("XAMS_RUN_DB", "run")
    run_collection: str = os.getenv("XAMS_RUN_COLLECTION", "runs_gas")
    processing_db: str = os.getenv("XAMS_PROCESSING_DB", "daq")
    processing_collection: str = os.getenv("XAMS_PROCESSING_COLLECTION", "processing")

    stbc_amstrax_dir: str = _cfg_env(
        "XAMS_STBC_AMSTRAX_DIR", "/data/xenon/xams_v2/software/amstrax/amstrax/auto_processing_new"
    )
    stbc_log_dir: str = _cfg_env("XAMS_STBC_LOG_DIR", "/data/xenon/xams_v2/logs")
    stbc_output_dir: str = _cfg_env(
        "XAMS_STBC_OUTPUT_DIR", _XAMS.get("XAMS_PROCESSED_FOLDER", "/data/xenon/xams_v2/xams_processed")
    )

    # Submission behaviour.
    # submit_mode: "on" = submit Condor jobs, "dry" = run auto_processing without
    # --production (nothing is submitted or written), "off" = refuse all submissions.
    submit_mode: str = _cfg_env("XAMS_DASH_SUBMIT", "on").strip().lower()
    # Passed to auto_processing.py --max_jobs (it counts runs with status submitted/running).
    max_jobs: int = int(_cfg_env("XAMS_DASH_MAX_JOBS", "25"))
    # Waiting list for runs refused because the job limit was reached.
    queue_file: str = _cfg_env(
        "XAMS_DASH_QUEUE_FILE", os.path.join(os.path.expanduser("~"), ".xams_dashboard_queue.json")
    )
    queue_interval_s: int = int(_cfg_env("XAMS_DASH_QUEUE_INTERVAL", "120"))
    # Condor user whose jobs are shown / used for stale-status detection.
    condor_user: str = _cfg_env("XAMS_DASH_CONDOR_USER", "")
    # Where auto_processing.py (called for each submission) writes its own log and job files.
    ap_log_dir: str = _cfg_env("XAMS_DASH_AP_LOG_DIR", _cfg_env("XAMS_STBC_LOG_DIR", "/data/xenon/xams_v2/logs"))


settings = Settings()
