#!/usr/bin/env bash
# Private dashboard (docs/PRIVATE_MODE_PLAN.md): start / stop / status, as yourself, from your own checkout.
#   ops/start_private.sh [start|stop|status|url]
# Settings: ~/.xams/private.json (XAMS_PRIVATE_SETTINGS for another file); a token is added on the first start.
# Port: "dashboard_port" of the settings (default 20000 + uid % 20000). Open it from your machine with
#   ssh -N -L <local port>:127.0.0.1:<port> stbc-i1     then the link printed by "url" (with the token)
set -euo pipefail
APP_DIR=$(cd "$(dirname "$0")/.." && pwd)
SCREEN_NAME=${XAMS_PRIVATE_SCREEN:-xams_dashboard_private}
SETTINGS=${XAMS_PRIVATE_SETTINGS:-$HOME/.xams/private.json}
ENV_ACTIVATE=${XAMS_DASH_ENV_ACTIVATE:-"source /data/xenon/xams_v2/setup.sh"}
LOG=${XAMS_PRIVATE_LOG:-}

running() { screen -ls | grep -q "[.]$SCREEN_NAME[[:space:]]"; }
setting() { python3 -c "import json,os,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2]) or (20000 + os.getuid() % 20000 if sys.argv[2] == 'dashboard_port' else ''))" "$SETTINGS" "$1"; }

[ -f "$SETTINGS" ] || { echo "no settings file $SETTINGS (see backend/private/settings.py)"; exit 1; }
PORT=$(setting dashboard_port)
FOLDER=$(setting strax_folder)
[ -n "$LOG" ] || LOG="$FOLDER/.dashboard_private.log"     # not in the home (small quota)

case "${1:-start}" in
    stop)
        running && screen -S "$SCREEN_NAME" -X quit && echo "stopped $SCREEN_NAME" || echo "$SCREEN_NAME not running" ;;
    status)
        running && echo "screen $SCREEN_NAME running" || echo "screen $SCREEN_NAME not running"
        ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORT " && echo "port $PORT listening" || echo "port $PORT not listening" ;;
    url)
        echo "http://127.0.0.1:<local port>/?token=$(setting token)   (tunnel to stbc port $PORT)" ;;
    start)
        if running; then echo "$SCREEN_NAME already running (port $PORT)"; exit 0; fi
        # a token on the first start: only the owner of the settings file can read it
        if [ -z "$(setting token)" ]; then
            python3 - "$SETTINGS" <<'PY'
import json, secrets, sys
p = sys.argv[1]; d = json.load(open(p)); d["token"] = secrets.token_urlsafe(24)
json.dump(d, open(p, "w"), indent=1)
PY
            echo "token added to $SETTINGS"
        fi
        chmod 600 "$SETTINGS"
        touch "$LOG" && chmod 600 "$LOG"                   # only you: it lists your requests
        screen -S "$SCREEN_NAME" -dm bash -lc "umask 077 && cd '$APP_DIR' && $ENV_ACTIVATE && export XAMS_PRIVATE_SETTINGS='$SETTINGS' XAMS_CONFIG_FILE=~/.xams_config && exec python -m v2.private_app >> '$LOG' 2>&1"
        sleep 5
        running && echo "started $SCREEN_NAME on 127.0.0.1:$PORT (log $LOG)" || { echo "failed to start; see $LOG"; exit 1; } ;;
    *)
        echo "usage: $0 [start|stop|status|url]"; exit 2 ;;
esac
