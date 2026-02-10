#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ops/*.sh -> repo root
BASE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ENV_FILE="${BASE_DIR}/.env"
VENV_DIR="${BASE_DIR}/.venv"
VENV_BIN="${VENV_DIR}/bin"

if [[ -x "${VENV_BIN}/activate" ]]; then
  # shellcheck disable=SC1090
  source "${VENV_BIN}/activate"
fi

read_env_token() {
  if [[ -f "${ENV_FILE}" ]]; then
    grep -E "^ORCH_TOKEN=" "${ENV_FILE}" | head -n 1 | cut -d'=' -f2-
  fi
}

ORCH_TOKEN="${ORCH_TOKEN:-$(read_env_token || true)}"

if [[ -z "${ORCH_TOKEN}" ]]; then
  echo "[INFO] ORCH_TOKEN no encontrado. Generando uno nuevo..."
  ORCH_TOKEN="$(python - <<'PY'
import base64
import os

print(base64.b64encode(os.urandom(32)).decode())
PY
  )"

  python - <<PY
from pathlib import Path

env_file = Path("${ENV_FILE}")
token = "${ORCH_TOKEN}"
lines = []
found = False
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ORCH_TOKEN="):
            lines.append(f"ORCH_TOKEN={token}")
            found = True
        else:
            lines.append(line)
if not found:
    lines.append(f"ORCH_TOKEN={token}")
env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  echo "[OK] Token guardado en ${ENV_FILE}"
fi

echo "[HARDENING] Checking for existing instances on port 9325..."
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti :9325 || true)"
elif command -v ss >/dev/null 2>&1; then
  PIDS="$(ss -lptn "sport = :9325" 2>/dev/null | awk 'NR>1 {print $6}' | sed -E 's/.*pid=([0-9]+).*/\1/' || true)"
else
  PIDS=""
fi

if [[ -n "${PIDS}" ]]; then
  echo "[CLEANUP] Found existing process(es) (${PIDS}). Terminating..."
  kill -9 ${PIDS} >/dev/null 2>&1 || true
fi

echo "[START] Launching GIL Orchestrator..."
cd "${BASE_DIR}"

if command -v uvicorn >/dev/null 2>&1; then
  uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
elif [[ -x "${VENV_BIN}/python" ]]; then
  "${VENV_BIN}/python" -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
else
  echo "[ERROR] uvicorn no disponible. Activa un venv con dependencias instaladas."
  exit 1
fi
