#!/usr/bin/env bash
# Exercises real PostgreSQL authentication in an isolated disposable container.
set -euo pipefail
probe_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_image="${PROBE_POSTGRES_IMAGE:-postgres:18}"
probe_container="$(docker run --detach --network none --env POSTGRES_PASSWORD=fixture-admin "$probe_image")"
trap 'docker rm --force --volumes "$probe_container" >/dev/null' EXIT
probe_ready=false
for ((attempt = 0; attempt < 60; attempt++)); do
  if docker exec "$probe_container" pg_isready --host 127.0.0.1 --username postgres >/dev/null 2>&1; then
    probe_ready=true
    break
  fi
  sleep 1
done
if [[ "$probe_ready" != true ]]; then
  echo 'FAIL: database did not become ready' >&2
  exit 1
fi
docker exec -i "$probe_container" psql -X --username postgres --set ON_ERROR_STOP=1 < "$probe_dir/database.sql" >/dev/null
for probe_role in probe_a probe_b; do
  case "$probe_role" in
    probe_a) probe_password=fixture-a; probe_other=probe_b ;;
    probe_b) probe_password=fixture-b; probe_other=probe_a ;;
  esac
  probe_value="$(docker exec --env PGPASSWORD="$probe_password" "$probe_container" psql -X -w --host 127.0.0.1 --username "$probe_role" --dbname "$probe_role" --set ON_ERROR_STOP=1 --tuples-only --no-align --command 'CREATE TABLE isolation_probe (value text); INSERT INTO isolation_probe VALUES ('"'own database works'"'); SELECT value FROM isolation_probe;' | tail -n 1)"
  [[ "$probe_value" == 'own database works' ]]
  echo "PASS: $probe_role can initialize, write and read its database"
  for probe_database in "$probe_other" postgres template1; do
    if probe_error="$(docker exec --env PGPASSWORD="$probe_password" "$probe_container" psql -X -w --host 127.0.0.1 --username "$probe_role" --dbname "$probe_database" --command 'SELECT 1' 2>&1)"; then
      echo "FAIL: $probe_role connected to $probe_database" >&2
      exit 1
    fi
    if [[ "$probe_error" != *'permission denied for database'* ]]; then
      echo 'FAIL: connection failed without demonstrating database authorization denial' >&2
      exit 1
    fi
    echo "PASS: $probe_role denied connection to $probe_database"
  done
done
docker image inspect "$probe_image" --format 'Image: {{index .RepoDigests 0}}'
