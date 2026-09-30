#!/usr/bin/env bash
set -euo pipefail

SCREEN_NAME=${XAMS_AUTOPROC_SCREEN_NAME:-xams_auto_processing_online}
AMSTRAX_DIR=${XAMS_STBC_AMSTRAX_DIR:-/data/xenon/xams_v2/software/amstrax/amstrax/auto_processing_new}
TARGET=${XAMS_AUTOPROC_TARGET:-"raw_records peak_basics event_basics event_positions event_info"}
MEM=${XAMS_AUTOPROC_MEM:-16000}
MAX_JOBS=${XAMS_AUTOPROC_MAX_JOBS:-25}
QUEUE=${XAMS_AUTOPROC_QUEUE:-short}
MIN_RUN_NUMBER=${XAMS_AUTOPROC_MIN_RUN_NUMBER:-6000}
ENV_ACTIVATE=${XAMS_DASH_ENV_ACTIVATE:-"source /data/xenon/xams_v2/setup.sh"}

screen -S "$SCREEN_NAME" -X quit || true
screen -S "$SCREEN_NAME" -dm bash -lc "cd '$AMSTRAX_DIR' && $ENV_ACTIVATE && python auto_processing.py --target $TARGET --production --mem $MEM --max_jobs $MAX_JOBS --queue $QUEUE --min_run_number $MIN_RUN_NUMBER"

echo "Started auto_processing screen '$SCREEN_NAME' target=$TARGET mem=$MEM max_jobs=$MAX_JOBS queue=$QUEUE"
