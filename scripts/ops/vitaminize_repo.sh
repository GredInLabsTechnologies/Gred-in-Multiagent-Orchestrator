#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: ./scripts/ops/vitaminize_repo.sh -r <repo_path> -t <orch_token> [-b <api_base>]"
  echo "  -r  Ruta del repo a activar"
  echo "  -t  ORCH_TOKEN"
  echo "  -b  API base (default: http://127.0.0.1:9325)"
}

API_BASE="http://127.0.0.1:9325"
REPO_PATH=""
ORCH_TOKEN=""

while getopts "r:t:b:" opt; do
  case "${opt}" in
    r) REPO_PATH="${OPTARG}" ;;
    t) ORCH_TOKEN="${OPTARG}" ;;
    b) API_BASE="${OPTARG}" ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "${REPO_PATH}" || -z "${ORCH_TOKEN}" ]]; then
  usage
  exit 1
fi

if command -v python >/dev/null 2>&1; then
  ENCODED_PATH="$(python - <<PY
import urllib.parse
print(urllib.parse.quote("${REPO_PATH}"))
PY
  )"
else
  ENCODED_PATH="${REPO_PATH}"
fi

echo "Vitaminizando repo: ${REPO_PATH}"
curl -sS -X POST "${API_BASE}/ui/repos/vitaminize?path=${ENCODED_PATH}" \
  -H "Authorization: Bearer ${ORCH_TOKEN}" >/dev/null

echo "Repo activado y listo."
curl -sS -X POST "${API_BASE}/ui/repos/open?path=${ENCODED_PATH}" \
  -H "Authorization: Bearer ${ORCH_TOKEN}" >/dev/null
