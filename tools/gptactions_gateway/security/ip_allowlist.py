"""
IP Allowlist para el gateway de GPT Actions.

OpenAI publica los rangos de egress de ChatGPT Actions.
Este módulo mantiene un allowlist local sincronizable y lo aplica
como middleware de primera línea.

Política de fallo seguro:
  - Si el archivo no existe → DENEGAR todo (excepto localhost en modo dev)
  - Si el archivo está corrupto → DENEGAR todo
  - Si el archivo está obsoleto (> MAX_AGE_SECONDS) → PERMITIR pero loggear advertencia

El archivo de allowlist tiene el formato:
    {
        "fetched_at": "2026-02-21T10:00:00Z",
        "fetched_at_epoch": 1740128400.0,
        "source_url": "https://...",
        "content_hash": "sha256-of-raw-content",
        "cidrs": ["23.102.140.112/28", "13.66.11.96/28", ...]
    }
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("gptactions.ip_allowlist")

# Tiempo en segundos antes de considerar el allowlist obsoleto (12 horas)
MAX_AGE_SECONDS = 43200

# Tiempo de recarga en memoria (evita leer disco en cada request)
MEMORY_REFRESH_SECONDS = 300


class IPAllowlist:
    """
    Allowlist de IPs thread-safe con soporte de CIDR.

    Carga el allowlist desde un archivo JSON.
    Recarga automáticamente desde disco cada MEMORY_REFRESH_SECONDS.
    """

    def __init__(
        self,
        allowlist_path: Path,
        bypass_loopback: bool = False,
        bypass_private: bool = False,
    ) -> None:
        """
        Args:
            allowlist_path: Ruta al archivo JSON de allowlist.
            bypass_loopback: Si True, permite IPs de loopback (127.x, ::1).
                             Solo para desarrollo local.
            bypass_private: Si True, permite IPs privadas RFC-1918.
                            Solo para pruebas en red interna.
        """
        self._path = allowlist_path
        self._bypass_loopback = bypass_loopback
        self._bypass_private = bypass_private
        self._lock = threading.RLock()
        self._networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self._loaded_at: float = 0.0
        self._fetched_at_epoch: float = 0.0
        self._reload()

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        """Carga (o recarga) el allowlist desde disco."""
        if not self._path.exists():
            logger.warning(
                "Archivo de allowlist de IPs no encontrado: %s — "
                "TODAS las IPs externas serán BLOQUEADAS",
                self._path,
            )
            with self._lock:
                self._networks = []
                self._loaded_at = time.time()
                self._fetched_at_epoch = 0.0
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            cidrs: list[str] = data.get("cidrs", [])
            networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
            for cidr in cidrs:
                try:
                    networks.append(ipaddress.ip_network(cidr, strict=False))
                except ValueError:
                    logger.warning("CIDR inválido en allowlist: %r", cidr)

            with self._lock:
                self._networks = networks
                self._loaded_at = time.time()
                self._fetched_at_epoch = float(data.get("fetched_at_epoch", 0))

            logger.info(
                "Allowlist de IPs cargado: %d CIDRs (actualizado: %s)",
                len(networks),
                data.get("fetched_at", "desconocido"),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Error al cargar allowlist de IPs: %s — bloqueando todo", exc)
            with self._lock:
                self._networks = []
                self._loaded_at = time.time()

    def _maybe_reload(self) -> None:
        """Recarga si la copia en memoria tiene más de MEMORY_REFRESH_SECONDS."""
        if time.time() - self._loaded_at > MEMORY_REFRESH_SECONDS:
            self._reload()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def is_allowed(self, ip_str: str) -> tuple[bool, str]:
        """
        Determina si una IP está permitida.

        Returns:
            (True, reason)  si está permitida
            (False, reason) si está bloqueada
        """
        self._maybe_reload()

        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"IP inválida: {ip_str!r}"

        # Bypasses de desarrollo (solo cuando están explícitamente habilitados)
        if self._bypass_loopback and addr.is_loopback:
            return True, "loopback-bypass"
        if self._bypass_private and addr.is_private:
            return True, "private-bypass"

        with self._lock:
            if not self._networks:
                return False, "allowlist-vacío"
            for net in self._networks:
                if addr in net:
                    return True, f"cidr-match:{net}"
            return False, "no-match"

    @property
    def is_stale(self) -> bool:
        """True si los datos del archivo tienen más de MAX_AGE_SECONDS."""
        if not self._path.exists():
            return True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            epoch = float(data.get("fetched_at_epoch", 0))
            return (time.time() - epoch) > MAX_AGE_SECONDS
        except Exception:
            return True

    @property
    def cidr_count(self) -> int:
        with self._lock:
            return len(self._networks)

    def force_reload(self) -> None:
        """Fuerza recarga desde disco (útil tras sync_openai_ips.py)."""
        self._reload()
