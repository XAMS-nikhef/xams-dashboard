"""The users of the XAMS dashboards: users.yaml at the top of the repository (XAMS_DASH_USERS_FILE for another file).

Names, STBC accounts, the ports of their private servers and who may act on the central dashboard. No secrets: the
keys live in the accounts' homes (central: backend/common/keys.py; private: the token in ~/.xams/private.json).

    from backend.common import users
    users.for_account("z37")            # User(name="acolijn", ...) or None
    users.may_act_centrally("acolijn")  # True only with central_actions: true

A missing or invalid file means no users: nobody acts centrally (fail closed) and private ports fall back to the
default per user id.
"""
from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "users.yaml"


@dataclass(frozen=True)
class User:
    name: str
    account: str
    dashboard_port: int | None = None
    sim_port: int | None = None
    central_actions: bool = False


def path() -> Path:
    return Path(os.environ.get("XAMS_DASH_USERS_FILE") or DEFAULT_FILE)


_CACHE: dict = {}                     # path -> (mtime, {name: User})


def _port(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if 1024 < v < 65536 else None


def load() -> dict:
    """{name: User}; {} when the file is missing or not valid."""
    p = path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        import yaml
        raw = (yaml.safe_load(p.read_text()) or {}).get("users") or {}
        out = {}
        for name, d in raw.items():
            d = d or {}
            out[str(name)] = User(name=str(name), account=str(d.get("account") or name),
                                  dashboard_port=_port(d.get("dashboard_port")), sim_port=_port(d.get("sim_port")),
                                  central_actions=d.get("central_actions") is True)
    except Exception:                                                # noqa: BLE001  (bad file: no users)
        out = {}
    _CACHE[str(p)] = (mtime, out)
    return out


def for_account(account: str | None = None) -> User | None:
    """The user whose STBC account this is (default: the account running this process)."""
    account = account or getpass.getuser()
    return next((u for u in load().values() if u.account == account), None)


def may_act_centrally(name: str | None) -> bool:
    u = load().get(name or "")
    return bool(u and u.central_actions)
