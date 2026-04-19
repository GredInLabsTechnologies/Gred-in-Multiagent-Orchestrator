"""mDNS advertiser for GIMO Mesh Core discovery.

Registers a ``_gimo._tcp.local.`` service on the LAN so Android devices
can auto-discover the Core without the user typing a URL.

**Security hardening**:
- Disabled by default — requires ``ORCH_MDNS_ENABLED=true`` env var **OR**
  the host is bootstrapped with ``device_mode=server`` (auto-enable per rev 2).
- TXT record includes HMAC-SHA256 signature (32 hex chars, NIST-truncated)
  derived from ORCH_TOKEN so clients can verify the announcement is authentic.
- Advertises hostname, port, version, mesh_enabled — plus health/mode/load
  as routing signals (rev 2). No secrets.

Usage::

    advertiser = MdnsAdvertiser(port=9325, token="my-orch-token")
    advertiser.start()   # registers service
    # ... server runs ...
    advertiser.update_signals(health=87, mode="server", load=0.3)  # rev 2
    # ...
    advertiser.stop()    # unregisters + closes
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

logger = logging.getLogger("orchestrator.mesh.mdns")

_VERSION = "1.0.0"


class MdnsAdvertiser:
    """Zeroconf service advertiser for ``_gimo._tcp.local.``."""

    SERVICE_TYPE = "_gimo._tcp.local."

    def __init__(self, port: int = 9325, token: str = "", runtime_version: str = ""):
        self._port = port
        self._token = token
        self._zc = None  # Zeroconf instance
        self._info = None  # ServiceInfo instance
        self._started = False
        # rev 2: runtime signals published as TXT record fields
        self._health: int = 100
        self._mode: str = "inference"
        self._load: float = 0.0
        # Runtime packaging (plan 2026-04-16, Change 5): publishes the Core's
        # bundle version so peers can decide if they need to upgrade without
        # hitting /ops/mesh/runtime-manifest first. Empty string = unknown
        # (legacy Cores pre-runtime-packaging).
        self._runtime_version: str = runtime_version or ""

    def start(self) -> None:
        """Register the mDNS service. Idempotent."""
        if self._started:
            logger.debug("mDNS advertiser already running")
            return

        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            logger.warning(
                "zeroconf package not installed — mDNS disabled. "
                "Install with: pip install zeroconf>=0.132.0"
            )
            return

        hostname = socket.gethostname()
        service_name = f"gimo-{hostname}.{self.SERVICE_TYPE}"

        # Resolve local IP (best effort — fallback to 127.0.0.1)
        local_ip = _get_local_ip()

        properties = self._build_properties(hostname)

        try:
            self._info = ServiceInfo(
                type_=self.SERVICE_TYPE,
                name=service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=self._port,
                properties=properties,
                server=f"{hostname}.local.",
            )
            self._zc = Zeroconf()
            self._zc.register_service(self._info)
            self._started = True
            logger.info(
                "mDNS advertiser started: %s on %s:%d (mode=%s, health=%d, load=%.2f, runtime=%s)",
                service_name, local_ip, self._port, self._mode, self._health, self._load,
                self._runtime_version or "-",
            )
        except Exception:
            logger.exception("Failed to start mDNS advertiser")
            self._cleanup()

    def stop(self) -> None:
        """Unregister the service and close Zeroconf. Idempotent."""
        if not self._started:
            return
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
                logger.info("mDNS service unregistered")
        except Exception:
            logger.warning("Error unregistering mDNS service", exc_info=True)
        self._cleanup()

    # ── Runtime signal updates (rev 2) ────────────────────────
    def update_signals(
        self,
        *,
        health: Optional[int] = None,
        mode: Optional[str] = None,
        load: Optional[float] = None,
        runtime_version: Optional[str] = None,
    ) -> None:
        """Update health/mode/load/runtime_version signals and re-publish TXT record.

        Best-effort: if Zeroconf update fails, signals are still recorded so
        the next restart publishes them.
        """
        changed = False
        if health is not None and health != self._health:
            self._health = max(0, min(100, int(health)))
            changed = True
        if mode is not None and mode != self._mode:
            self._mode = mode
            changed = True
        if load is not None:
            clamped = max(0.0, min(1.0, float(load)))
            if abs(clamped - self._load) >= 0.05:  # 5% deadband
                self._load = clamped
                changed = True
        if runtime_version is not None and runtime_version != self._runtime_version:
            self._runtime_version = runtime_version
            changed = True

        if not changed or not self._started or self._zc is None or self._info is None:
            return

        try:
            hostname = socket.gethostname()
            self._info.properties = self._encode_properties(self._build_properties(hostname))
            self._zc.update_service(self._info)
            logger.debug(
                "mDNS signals updated: mode=%s, health=%d, load=%.2f",
                self._mode, self._health, self._load,
            )
        except Exception:
            logger.debug("mDNS update_service failed", exc_info=True)

    @property
    def is_running(self) -> bool:
        return self._started

    # ── Internals ─────────────────────────────────────────────

    def _build_properties(self, hostname: str) -> dict:
        """Compose TXT record properties (rev 2: health/mode/load; runtime pkg: runtime_version)."""
        from tools.gimo_server.services.mesh.hmac_signer import sign_payload

        # HMAC covers hostname, port AND the live signals so a MITM cannot
        # spoof a healthy peer — any tampering invalidates the signature.
        # runtime_version is included so a peer cannot spoof a newer bundle.
        payload_to_sign = (
            f"{hostname}:{self._port}:{self._mode}:{self._health}:{self._load:.2f}"
            f":{self._runtime_version}"
        )
        hmac_sig = sign_payload(self._token, payload_to_sign) if self._token else ""

        return {
            "version": _VERSION,
            "mesh": "true",
            "core_id": "gimo",
            "hmac": hmac_sig,
            # rev 2 — routing signals (unsigned individually but covered by HMAC above)
            "mode": self._mode,
            "health": str(self._health),
            "load": f"{self._load:.2f}",
            # runtime packaging (plan 2026-04-16): bundle version for upgrade hints
            "runtime_version": self._runtime_version,
        }

    @staticmethod
    def _encode_properties(props: dict) -> dict:
        """Encode string values to bytes as zeroconf expects."""
        return {k: (v.encode("utf-8") if isinstance(v, str) else v) for k, v in props.items()}

    def _cleanup(self) -> None:
        if self._zc:
            try:
                self._zc.close()
            except Exception:
                pass
        self._zc = None
        self._info = None
        self._started = False


def _get_local_ip() -> str:
    """Best-effort detection of the host's LAN IP address."""
    try:
        # Connect to a non-routable address to find the default interface IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
