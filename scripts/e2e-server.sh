#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_dir="$(mktemp -d)"

cleanup() {
  rm -rf "$workspace_dir"
}
trap cleanup EXIT

cp -R "$repo_dir/examples/incidents/." "$workspace_dir/"
cd "$repo_dir"
uv run graphkit review \
  --workspace "$workspace_dir" \
  --port 8877 \
  --no-open-browser
