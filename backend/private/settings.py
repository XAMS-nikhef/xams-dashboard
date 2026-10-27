"""The user's settings of the private apps: one JSON file, default ~/.xams/private.json (XAMS_PRIVATE_SETTINGS to use
another). Read by the private dashboard (and later the private simulation app and the launcher's Settings tile).

    {
      "strax_folder": "/data/xenon/xams_v2/users/<you>/measurements/strax_data",
      "token": "<secret>",                      # required by the app on every request (made by ops/start_private.sh)
      "dashboard_port": 21234,                  # remote port of the private dashboard (default from the user id)
      "contexts": [                             # context providers: a data set is current if one of them makes it
        {"name": "SR2026.3", "python": "/path/to/python", "path": ".../analysis_SR2026.3/lib/xams_sr.py",
         "call": "context_for_runs", "args": [["{run}"]], "watch": [".../analysis_SR2026.3/config"]},
        {"name": "central", "kind": "amstrax", "context": "xams", "config": {}}
      ],
      "max_jobs": 10                            # for the Process button (later)
    }
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def settings_path() -> Path:
    return Path(os.environ.get("XAMS_PRIVATE_SETTINGS") or Path.home() / ".xams" / "private.json")


def default_port() -> int:
    """A port per user, so that two users' private dashboards on one host do not collide."""
    return 20000 + os.getuid() % 20000


@dataclass
class PrivateSettings:
    strax_folder: Path
    token: str = ""
    dashboard_port: int = field(default_factory=default_port)
    contexts: list = field(default_factory=list)
    max_jobs: int = 10
    path: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "PrivateSettings":
        path = Path(path or settings_path())
        if not path.exists():
            raise FileNotFoundError(f"no private settings file {path} (see backend/private/settings.py)")
        d = json.loads(path.read_text())
        if not d.get("strax_folder"):
            raise ValueError(f"{path}: 'strax_folder' is missing")
        return cls(strax_folder=Path(d["strax_folder"]), token=str(d.get("token") or ""),
                   dashboard_port=int(d.get("dashboard_port") or default_port()),
                   contexts=list(d.get("contexts") or []), max_jobs=int(d.get("max_jobs") or 10), path=path)
