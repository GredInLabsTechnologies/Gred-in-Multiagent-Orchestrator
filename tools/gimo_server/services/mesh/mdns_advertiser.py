"""mDNS advertiser for GIMO Mesh Core discovery.

Registers a ``_gimo._tcp.local.`` service on the LAN so Android devices
can auto-discover the Core without the user typing a URL.

**Security hardening**:
- Disabled by default — requires ``ORCH_MDNS_ENABLED=true`` env var.
- TXT record includes HMAC-SHA256 signature (first 16 hex chars) derived
  from ORCH_TOKEN so clients can verify the announcement is authentic.
- Only advertises hostname, port, version, mesh_enabled — no secrets.

Usage::

    advertiser = MdnsAdvertiser(port=9325, token="my-orch-token")
    advertiser.start()   # registers service
    # ... server runs ...
    advertiser.stop()    # unregisters + closes
"""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger("orchestrator.mesh.mdns")

_VERSION = "1.0.0"


class MdnsAdvertiser:
    """Zeroconf service advertiser for ``_gimo._tcp.local.``."""

    SERVICE_TYPE = "_gimo._tcp.local."

    def __init__(self, port: int = 9325, token: str = ""):
        self._port = port
        self._token = token
        self._zc = None  # Zeroconf instance
        self._info = None  # ServiceInfo instance
        self._started = False

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

        # Build TXT record properties
        from tools.gimo_server.services.mesh.hmac_signer import sign_payload

        payload_to_sign = f"{hostname}:{self._port}"
        hmac_sig = sign_payload(self._token, payload_to_sign) if self._token else ""

        properties = {
            "version": _VERSION,
            "mesh": "true",
            "core_id": "gimo",
            "hmac": hmac_sig,
        }

        # Resolve local IP (best effort — fallback to 0.0.0.0)
        local_ip = _get_local_ip()

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
                "mDNS advertiser started: %s on %s:%d (hmac=%s)",
                service_name, local_ip, self._port, hmac_sig[:8] + "..." if hmac_sig else "none",
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

    @property
    def is_running(self) -> bool:
        return self._started

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
