#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="gil-orchestrator"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

usage() {
  echo "Usage: ./scripts/ops/manage_service.sh [install|uninstall|start|stop|status|restart]"
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

ACTION="${1}"

case "${ACTION}" in
  install)
    if [[ $EUID -ne 0 ]]; then
      echo "[ERROR] install requiere permisos de root (sudo)."
      exit 1
    fi

    # scripts/ops/*.sh -> repo root
    ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    cat > "${SERVICE_FILE}" <<SERVICE
[Unit]
Description=GIL Orchestrator Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONPATH=${ROOT_DIR}
EnvironmentFile=${ROOT_DIR}/.env
ExecStart=/usr/bin/env uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    echo "[OK] Servicio ${SERVICE_NAME} instalado."
    ;;
  uninstall)
    if [[ $EUID -ne 0 ]]; then
      echo "[ERROR] uninstall requiere permisos de root (sudo)."
      exit 1
    fi
    systemctl disable "${SERVICE_NAME}" || true
    systemctl stop "${SERVICE_NAME}" || true
    rm -f "${SERVICE_FILE}"
    systemctl daemon-reload
    echo "[OK] Servicio ${SERVICE_NAME} eliminado."
    ;;
  start)
    systemctl start "${SERVICE_NAME}"
    ;;
  stop)
    systemctl stop "${SERVICE_NAME}"
    ;;
  status)
    systemctl status "${SERVICE_NAME}"
    ;;
  restart)
    systemctl restart "${SERVICE_NAME}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
