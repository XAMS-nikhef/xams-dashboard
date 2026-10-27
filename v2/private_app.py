"""Private dashboard: the processed data in the user's own strax folder (docs/PRIVATE_MODE_PLAN.md).

Run as the user, from their own checkout:  ops/start_private.sh   (settings ~/.xams/private.json)
The page and its API are the shared data view (v2/dataview.py) with the profile "private"; this app adds the token:
every request needs the token of the settings (?token=... once, then a cookie), so other users on the same host
cannot use it.
"""
from __future__ import annotations

import hmac
import logging
import re

from flask import Flask, abort, make_response, redirect, request

from backend.common.profile import private_profile
from backend.private.settings import PrivateSettings
from v2.dataview import blueprint

S = PrivateSettings.load()
app = Flask(__name__, template_folder="templates", static_folder="static")
COOKIE = "xams_private_token"
_bp = blueprint(private_profile(S), base="")
view = _bp.view
app.register_blueprint(_bp)


# ------------------------------------------------------------------------------------------------ access
class _HideToken(logging.Filter):
    """The request log must not show the token (the log file may be readable by others)."""
    def filter(self, record):
        record.msg = re.sub(r"token=[^\s&\"]+", "token=***", str(record.msg))
        if record.args:
            record.args = tuple(re.sub(r"token=[^\s&\"]+", "token=***", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


logging.getLogger("werkzeug").addFilter(_HideToken())


def _token_ok(value) -> bool:
    return bool(S.token) and bool(value) and hmac.compare_digest(str(value), S.token)


@app.before_request
def _check_token():
    if not S.token:
        abort(make_response("no token in the private settings: start the app with ops/start_private.sh", 403))
    if not (_token_ok(request.args.get("token")) or _token_ok(request.cookies.get(COOKIE))
            or _token_ok(request.headers.get("X-Token"))):
        abort(make_response("forbidden: open the private dashboard with its token (launcher, or the link printed by "
                            "ops/start_private.sh)", 403))


@app.after_request
def _set_cookie(resp):
    if _token_ok(request.args.get("token")):
        resp.set_cookie(COOKIE, S.token, httponly=True, samesite="Strict", max_age=30 * 24 * 3600)
    resp.headers["Cache-Control"] = "no-cache"               # after an update the browser fetches the new page / JS
    return resp


@app.before_request
def _drop_token_from_url():
    """A page opened with ?token=: the cookie is set, then the same page without the token in its address."""
    if request.method == "GET" and request.path == "/" and request.args.get("token"):
        return redirect("/", code=302)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=S.dashboard_port, debug=False)
