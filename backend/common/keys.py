"""Keys for the actions of the production dashboard (old page and /v3).

Every request that changes something (POST: delete, submit, queue, backfill) needs the key of a user on the list;
reading needs none. Other users on stbc-i1 can reach 127.0.0.1:8070 too, so without keys anyone logged in there
could delete central data as xamsdata.

Keys file: XAMS_DASH_KEYS_FILE, default ~/.xams_dashboard_keys.json of the account that runs the dashboard
(xamsdata), mode 600: {"users": {"acolijn": "<key>"}}. No file, an unreadable file or an empty list: every action
is refused (fail closed). The browser gets the key once as ?key=... (the launcher's /open/dashboard), then as a
cookie.

    python -m backend.common.keys add acolijn       new key for a user (printed once)
    python -m backend.common.keys remove acolijn
    python -m backend.common.keys list              names only
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import sys
from pathlib import Path

COOKIE = "xams_dash_key"


def path() -> Path:
    return Path(os.environ.get("XAMS_DASH_KEYS_FILE", Path.home() / ".xams_dashboard_keys.json"))


_CACHE: dict = {}                     # path -> (mtime, {name: key})


def load() -> dict:
    """{name: key}; {} when the file is missing, unreadable, readable by others or not valid."""
    p = path()
    try:
        st = p.stat()
    except OSError:
        return {}
    if st.st_mode & 0o077:            # readable or writable by group / others: do not trust it
        return {}
    hit = _CACHE.get(str(p))
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    try:
        users = json.loads(p.read_text()).get("users") or {}
        users = {str(k): str(v) for k, v in users.items() if v and len(str(v)) >= 20}
    except (OSError, ValueError, AttributeError):
        users = {}
    _CACHE[str(p)] = (st.st_mtime, users)
    return users


def user_for(value) -> str | None:
    """The name whose key this is, or None."""
    if not value:
        return None
    for name, key in load().items():
        if hmac.compare_digest(str(value), key):
            return name
    return None


def _write(users: dict):
    p = path()
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"users": users}, f, indent=1)
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def add(name: str) -> str:
    users = dict(load())
    users[name] = secrets.token_urlsafe(32)
    _write(users)
    return users[name]


def remove(name: str) -> bool:
    users = dict(load())
    gone = users.pop(name, None) is not None
    _write(users)
    return gone


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["list"]
    if cmd == "add" and rest:
        print(f"key for {rest[0]} (shown once; keep it in ~/.xams-web/central_dashboard_key on your laptop):")
        print(add(rest[0]))
    elif cmd == "remove" and rest:
        print("removed" if remove(rest[0]) else "no such user")
    elif cmd == "list":
        print("\n".join(sorted(load())) or f"no users ({path()})")
    else:
        print(__doc__)
        sys.exit(1)
