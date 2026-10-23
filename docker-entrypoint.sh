#!/bin/sh
set -eu

# Render mounts the persistent disk after the image is built, so ownership
# must be repaired at startup. Then drop root before running the application.
DATA_ROOT="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_ROOT/auth"

if [ "$(id -u)" = "0" ]; then
    chown -R atlas:atlas "$DATA_ROOT"
    exec gosu atlas "$@"
fi

exec "$@"
