#!/usr/bin/env bash
# Stop the online auto-processing loop CLEANLY: SIGINT to the python process,
# which finishes the step it is in (never half a submission) and exits within
# seconds (amstrax auto_processing.py, clean stop). Only if it has not exited
# after XAMS_AUTOPROC_STOP_TIMEOUT seconds is the screen closed hard.
set -euo pipefail

SCREEN_NAME=${XAMS_AUTOPROC_SCREEN_NAME:-xams_auto_processing_online}
TIMEOUT=${XAMS_AUTOPROC_STOP_TIMEOUT:-120}
# ^python: the loop itself, not the `bash -lc` wrapper whose command line
# also contains "python auto_processing.py".
PATTERN='^python auto_processing.py'

pids=$(pgrep -u "$(id -u)" -f "$PATTERN" || true)
if [ -n "$pids" ]; then
    echo "Stopping auto_processing (pid $pids), waiting up to ${TIMEOUT}s ..."
    kill -INT $pids
    for _ in $(seq 1 "$TIMEOUT"); do
        pgrep -u "$(id -u)" -f "$PATTERN" >/dev/null || break
        sleep 1
    done
    if pgrep -u "$(id -u)" -f "$PATTERN" >/dev/null; then
        echo "WARNING: still running after ${TIMEOUT}s; closing the screen hard."
    else
        echo "auto_processing stopped cleanly."
    fi
else
    echo "No auto_processing loop running."
fi
screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
