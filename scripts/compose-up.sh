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
cd "$(dirname "$0")/.." || exit 1

# service:host-port, matching the ports docker-compose.yml publishes.
SERVICES=(
  "redis:56379"
  "elasticsearch:59200"
  "postgres:55432"
  "message-db:55433"
  "mssql:51433"
  "mysql:53306"
  "mariadb:53307"
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

# An open port is not readiness for MySQL and MariaDB. The server answers on
# 3306 while it is still running its first-run initialisation, before the
# `protean` database exists, so a `Domain.init()` right after this script can
# fail on a connection the port check called fine. CI waits for a real query
# for the same reason, and `make test-full` starts testing the moment this
# returns. Checked whether or not this run started them, because "already
# listening" is exactly the state that lies.
query_check() {  # <service>
  case "$1" in
    mysql)   echo 'mysql -h 127.0.0.1 -uroot -pprotean -e "SELECT 1" protean' ;;
    mariadb) echo 'mariadb -h 127.0.0.1 -uroot -pprotean -e "SELECT 1" protean' ;;
    *)       echo "" ;;
  esac
}

await_queries() {  # <service>:<host-port>...
  for entry in "$@"; do
    name="${entry%%:*}"; port="${entry##*:}"
    check="$(query_check "$name")"
    [ -n "$check" ] || continue

    echo "  waiting for $name to answer a query..."
    for _ in $(seq 1 60); do
      # Find the container by the port it publishes, not through this
      # checkout's Compose project. The port check above exists precisely
      # because the service may belong to another worktree's project, where
      # `docker-compose exec` here would find nothing and wait out the clock.
      # `--filter publish=` is Docker-only. Podman's docker-compatible CLI
      # rejects it with "publish is an invalid filter", so the lookup found
      # nothing on every try, waited out the full clock and failed `make up`
      # on a box where every service was up and answering. Both engines print
      # the published port in the Ports column, so match on that instead.
      container="$(docker ps --format '{{.Names}}\t{{.Ports}}' \
        | awk -F'\t' -v p=":$port->" 'index($2, p) { print $1; exit }')"
      if [ -n "$container" ] && docker exec "$container" sh -c "$check" >/dev/null 2>&1; then
        continue 2
      fi
      sleep 2
    done
    echo "  $name never answered SELECT 1 on $port; tests against it will fail" >&2
    exit 1
  done
}

if [ ${#missing[@]} -eq 0 ]; then
  echo "all backing services already up; nothing to start"
  await_queries "${SERVICES[@]}"
  exit 0
fi

echo "starting: ${missing[*]}"
docker-compose up -d "${missing[@]}"
await_queries "${SERVICES[@]}"
