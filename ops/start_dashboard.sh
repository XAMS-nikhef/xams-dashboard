#!/usr/bin/env bash
set -euo pipefail

# Settings that must survive a restart (e.g. XAMS_DASH_CURRENT_VERSIONS, XAMS_AUTOPROC_CORRECTIONS) live in this file,
# not in the shell that happens to run the restart. Plain KEY=value lines; variables already set win.
ENV_FILE=${XAMS_DASH_ENV_FILE:-$HOME/.xams_dashboard.env}
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ -z "${!key:-}" ]] && export "$key=$value"
  done < "$ENV_FILE"
fi

SCREEN_NAME=${XAMS_DASH_SCREEN_NAME:-xams_dashboard}
APP_DIR=${XAMS_DASH_APP_DIR:-$HOME/xams-dashboard}
HOST=${XAMS_DASH_HOST:-127.0.0.1}
PORT=${XAMS_DASH_PORT:-8070}
MAX_JOBS=${XAMS_DASH_MAX_JOBS:-100}
ENV_ACTIVATE=${XAMS_DASH_ENV_ACTIVATE:-"source /data/xenon/xams_v2/setup.sh"}

screen -S "$SCREEN_NAME" -X quit || true
screen -S "$SCREEN_NAME" -dm bash -lc "cd '$APP_DIR' && $ENV_ACTIVATE && export XAMS_DASH_HOST='$HOST' XAMS_DASH_PORT='$PORT' XAMS_DASH_MAX_JOBS='$MAX_JOBS' XAMS_CONFIG_FILE=~/.xams_config && python -m v2.app"

echo "Started dashboard screen '$SCREEN_NAME' on ${HOST}:${PORT}"
echo "  current versions: ${XAMS_DASH_CURRENT_VERSIONS:-PROD0,v4 (default)}; submit default: ${XAMS_AUTOPROC_CORRECTIONS:-PROD0 (default)}"
