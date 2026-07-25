#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
clean_dir="$(mktemp -d)"
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$clean_dir"
}
trap cleanup EXIT

cp -R "$repo_dir/examples/incidents" "$clean_dir/incidents"

cd "$repo_dir"
uv run graphkit validate --workspace "$clean_dir/incidents"
uv run graphkit build --workspace "$clean_dir/incidents"
uv run graphkit query \
  "Which team owns Authentication Service?" \
  --workspace "$clean_dir/incidents" \
  | grep -q '"recipe_id": "service_owner"'

uv run graphkit review \
  --workspace "$clean_dir/incidents" \
  --port 8876 \
  --no-open-browser \
  >"$clean_dir/server.log" 2>&1 &
server_pid="$!"

for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8876/healthz >/dev/null; then
    echo "README clean-room verification passed."
    exit 0
  fi
  sleep 0.2
done

cat "$clean_dir/server.log"
exit 1
