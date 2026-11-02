#!/bin/sh
# API container entrypoint.
#
# Order of operations:
#   1. best-effort wait until the Postgres host:port in SYNAPSE_DATABASE_URL
#      accepts TCP connections (depends_on: service_healthy usually makes this
#      instant; the wait covers restart ordering and slow volumes);
#   2. run `alembic upgrade head` *if* the migration tree is present;
#   3. exec uvicorn.
#
# Step 2 is deliberately tolerant. Auth + Alembic are landing in a separate
# slice, so an image built before that code exists must still boot and still
# serve the SQLite-backed diagnostic store. This script never invents a
# migration, never runs `create_all`, and never touches apps/api sources.
set -eu

wait_for_database() {
    # No SQLAlchemy URL configured: nothing to wait for (SQLite-only boot).
    [ -n "${SYNAPSE_DATABASE_URL:-}" ] || return 0

    python - "$SYNAPSE_DATABASE_URL" <<'PY'
import re
import socket
import sys
import time
from urllib.parse import urlsplit

raw = sys.argv[1]
# Strip a SQLAlchemy driver suffix: postgresql+psycopg://x -> postgresql://x
url = re.sub(r"^([A-Za-z0-9]+)(?:\+[A-Za-z0-9_]+)?://", r"\1://", raw)
parts = urlsplit(url)
if not parts.hostname:
    print(f"[entrypoint] no host in SYNAPSE_DATABASE_URL ({parts.scheme}); skipping DB wait")
    sys.exit(0)

host = parts.hostname
port = parts.port or 5432
deadline = time.monotonic() + 60
last_error: OSError | None = None
while True:
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"[entrypoint] database reachable at {host}:{port}")
            sys.exit(0)
    except OSError as exc:  # refused, DNS, timeout: retry until the deadline
        last_error = exc
        if time.monotonic() >= deadline:
            print(
                f"[entrypoint] database unreachable at {host}:{port} after 60s: {last_error}",
                file=sys.stderr,
            )
            sys.exit(1)
        time.sleep(1)
PY
}

wait_for_database

if [ -f alembic.ini ]; then
    if command -v alembic >/dev/null 2>&1; then
        echo "[entrypoint] alembic.ini found: alembic upgrade head"
        alembic upgrade head
    else
        echo "[entrypoint] alembic.ini found but the alembic CLI is not installed;" >&2
        echo "[entrypoint] add alembic to apps/api runtime deps and rebuild the image" >&2
        exit 1
    fi
else
    echo "[entrypoint] no alembic.ini: skipping migrations (SQLite stores only)"
fi

exec uvicorn synapse.api.main:app --host 0.0.0.0 --port 8000