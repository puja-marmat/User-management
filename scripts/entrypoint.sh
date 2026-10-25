#!/bin/sh
# Container entrypoint (plan §8). One image, four modes:
#   api                  (default) run the HTTP API
#   migrate              alembic upgrade head   (one-off job BEFORE the API rolls out)
#                        Phase 1: REFUSED unless IAM_MIGRATIONS_ENABLED=true (no schema changes)
#   migrate-sql          print the SQL of `alembic upgrade head` (review; no DB connection)
#   migration-cli ARGS   data migration CLI (arrives in M2)
#   sync                 Change Tracking sync worker (arrives in M7)
# The API never runs migrations at start-up.
set -eu

migrations_enabled() {
  v=$(printf '%s' "${IAM_MIGRATIONS_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')
  case "$v" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

mode="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$mode" in
  api)
    exec python -m app.entry_server
    ;;
  migrate)
    if ! migrations_enabled; then
      echo "migrate refused: Phase 1 allows no schema changes (U01 DEC-34, 00a §0.1)." >&2
      echo "Set IAM_MIGRATIONS_ENABLED=true only for an approved Phase 2 run or a CI scratch DB." >&2
      exit 78
    fi
    exec alembic upgrade head
    ;;
  migrate-sql)
    exec alembic upgrade head --sql
    ;;
  migration-cli)
    exec python -m app.migration "$@"
    ;;
  sync)
    exec python -m app.migration sync "$@"
    ;;
  *)
    echo "unknown mode: $mode (expected api | migrate | migrate-sql | migration-cli | sync)" >&2
    exit 64
    ;;
esac
