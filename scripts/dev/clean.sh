#!/usr/bin/env bash
set -euo pipefail

INCLUDE_ORCH_DATA=0
if [[ "${1:-}" == "--include-orch-data" ]]; then
  INCLUDE_ORCH_DATA=1
fi

rm_rf() {
  if [[ -e "$1" ]]; then
    echo "Removing $1"
    rm -rf "$1"
  fi
}

# Python / runtime artifacts
rm_rf .pytest_cache
rm_rf htmlcov
rm_rf .coverage
find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

rm_rf .orch_snapshots
if [[ $INCLUDE_ORCH_DATA -eq 1 ]]; then
  rm_rf .orch_data
fi

# UI artifacts
rm_rf tools/orchestrator_ui/coverage
rm_rf tools/orchestrator_ui/dist
rm_rf tools/orchestrator_ui/.turbo
rm_rf tools/orchestrator_ui/.vite

# Generated metrics
rm_rf out/metrics
rm_rf artifacts/metrics

echo "Clean completed."
