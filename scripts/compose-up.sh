#!/usr/bin/env bash
# compose-up.sh - bring up the test backing services, but only the ones that are
# not already listening.
#
# `docker-compose up` derives its project name from the directory, so running it
# from a git worktree tries to create a SECOND set of containers bound to the same
# host ports as the main checkout's. That fails with "address already in use" and
# takes the whole target down with it, which is how a `make test-full` from a
# worktree died on 2026-08-08 without running a single test.
#
# The services are shared and stateless for test purposes, so if a port is already
# answering, that service is usable as-is and there is nothing to start.
set -uo pipefail
cd "$(dirname "$0")/.."

# service:host-port, matching the ports docker-compose.yml publishes.
SERVICES=(
  "redis:56379"
  "elasticsearch:59200"
  "postgres:55432"
  "message-db:55433"
  "mssql:51433"
)

listening() {   # <port>
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$1" >/dev/null 2>&1 && return 0
    return 1
  fi
  # Fallback with no extra dependency.
  python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

missing=()
for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"; port="${entry##*:}"
  if listening "$port"; then
    echo "  $name already listening on $port, leaving it alone"
  else
    missing+=("$name")
  fi
done

if [ ${#missing[@]} -eq 0 ]; then
  echo "all backing services already up; nothing to start"
  exit 0
fi

echo "starting: ${missing[*]}"
docker-compose up -d "${missing[@]}"
