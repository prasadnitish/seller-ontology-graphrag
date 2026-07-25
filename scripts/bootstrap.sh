#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

uv sync --extra dev
npm --prefix frontend install
npm --prefix frontend run build
uv run graphkit schema --output docs/graphspec.schema.json

for workspace in examples/incidents examples/seller; do
  uv run graphkit profile --workspace "$workspace"
  uv run graphkit validate --workspace "$workspace"
done

echo "GraphRAG Ontology Workbench is ready."
