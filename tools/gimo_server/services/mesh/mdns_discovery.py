"""Client-side mDNS discovery for GIMO Mesh Core (rev 2 Cambio 10).

Browses the LAN for ``_gimo._tcp.local.`` services published by a GIMO Core
running in server mode and returns a short list of verified peers. Used by:

- ``gimo discover`` CLI subcommand — operator-facing zero-config discovery
- future Android ``MeshAgentService`` LAN scan — to find a nearby Core when
  the phone boots without a configured endpoint

**Security**: the TXT record includes an HMAC over
``hostname:port:mode:health:load:runtime_version``, keyed by the shared
``ORCH_TOKEN``. Announcements whose signature does not verify are returned with
``verified=False`` and should be displayed but not auto-connected.
Unsigned announcements (empty hmac, e.g. client-mode broadcasts) surface as
``verified=False`` as well — only a token match upgrades the flag.

Offline-safe: if ``zeroconf`` is not installed or no peer answers within the
timeout, an empty list is returned. No exception propagates to the caller.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("orchestrator.mesh.mdns_discovery")

_SERVICE_TYPE = "_gimo._tcp.local."


@dataclass
class DiscoveredPeer:
    """One verified or unverified LAN peer."""
    name: str
    host: str
    port: int
    url: str
    mode: str = "inference"
    health: int = 0
    load: float = 0.0
    version: str = ""
    runtime_version: str = ""
    verified: bool = False
    txt_raw: dict = field(default_factory=dict)
    # BUGS_LATENTES §H11 — compatibility status contra el runtime local del cliente.
    # "compatible": misma major version o ambos vacíos
    # "incompatible": major version difiere (wire protocol drift riesgoso)
    # "unknown": una de las dos versions está vacía / no parseable
    # Advisory only — NO bloquea la conexión, solo informa al operator.
    compatibility_status: str = "unknown"


# BUGS_LATENTES §H11 — semver compat helpers.
def _parse_semver(version: str) -> Optional[tuple[int, int, int]]:
    """Parse best-effort de ``major.minor.patch`` con sufijos ignorados.

    Ejemplos aceptados: "0.1.0", "1.2.3-rc1", "0.1.0-ci-42-android", "2".
    Devuelve None si no se puede derivar al menos un major integer.
    """
    if not version:
        return None
    head = version.split("+", 1)[0].split("-", 1)[0]  # strip local + prerelease
    parts = head.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    return (major, minor, patch)


def compute_compatibility(local_version: str, remote_version: str) -> str:
    """Advisory compat: compatible / incompatible / unknown.

    BUGS_LATENTES §H11. Usa sólo major version para el compat — minor/patch
    son considerados backward compatible por convention semver.
    """
    local_tuple = _parse_semver(local_version)
    remote_tuple = _parse_semver(remote_version)
    if local_tuple is None or remote_tuple is None:
        return "unknown"
    if local_tuple[0] != remote_tuple[0]:
        return "incompatible"
    return "compatible"


def discover_peers(
    token: str = "",
    timeout_seconds: float = 3.0,
    max_peers: int = 16,
    local_runtime_version: str = "",
) -> List[DiscoveredPeer]:
    """Browse the LAN for GIMO Core peers. Blocking, best-effort.

    Returns an empty list if zeroconf is unavailable. Peers are sorted:
    verified first, then by ``health`` descending, then by ``load`` ascending.

    Args:
        local_runtime_version: BUGS_LATENTES §H11. Si se provee el semver
            del runtime local, cada peer devuelto tendrá populated su
            ``compatibility_status`` contra esta versión (compatible /
            incompatible / unknown). Advisory — no afecta el sort ni excluye
            peers.
    """
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except ImportError:
        logger.warning(
            "zeroconf not installed — cannot discover peers. "
            "Install with: pip install zeroconf>=0.132.0"
        )
        return []

    from tools.gimo_server.services.mesh.hmac_signer import verify_payload

    peers: dict[str, DiscoveredPeer] = {}

    def _on_change(zc, service_type, name, state_change):  # type: ignore[no-untyped-def]
        if state_change != ServiceStateChange.Added:
            return
        try:
            info = zc.get_service_info(service_type, name, timeout=int(timeout_seconds * 1000))
            if info is None:
                return

            addrs = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
            host = addrs[0] if addrs else ""
            if not host and info.addresses:
                host = socket.inet_ntoa(info.addresses[0])
            port = info.port or 0
            url = f"http://{host}:{port}" if host and port else ""

            raw = info.properties or {}
            txt = {
                (k.decode() if isinstance(k, bytes) else str(k)):
                (v.decode() if isinstance(v, bytes) else ("" if v is None else str(v)))
                for k, v in raw.items()
            }

            mode = txt.get("mode", "inference")
            try:
                health = int(txt.get("health", "0"))
            except ValueError:
                health = 0
            try:
                load = float(txt.get("load", "0.0"))
            except ValueError:
                load = 0.0
            version = txt.get("version", "")
            runtime_version = txt.get("runtime_version", "")

            verified = False
            hmac_sig = txt.get("hmac", "")
            if token and hmac_sig:
                hostname = (info.server or "").rstrip(".")
                # The advertiser strips the trailing `.local.` and signs the bare hostname
                if hostname.endswith(".local"):
                    hostname = hostname[: -len(".local")]
                payload = (
                    f"{hostname}:{port}:{mode}:{health}:{load:.2f}:{runtime_version}"
                )
                verified = verify_payload(token, payload, hmac_sig)

            # BUGS_LATENTES §H11: compute advisory compat status.
            compat = compute_compatibility(local_runtime_version, runtime_version)

            peers[name] = DiscoveredPeer(
                name=name.replace("." + service_type, ""),
                host=host,
                port=port,
                url=url,
                mode=mode,
                health=health,
                load=load,
                version=version,
                runtime_version=runtime_version,
                verified=verified,
                txt_raw=txt,
                compatibility_status=compat,
            )
        except Exception:
            logger.debug("Failed to parse %s", name, exc_info=True)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, _SERVICE_TYPE, handlers=[_on_change])
        # Active wait — zeroconf dispatches on its own thread
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and len(peers) < max_peers:
            time.sleep(0.1)
    finally:
        try:
            zc.close()
        except Exception:
            pass

    results = list(peers.values())
    results.sort(key=lambda p: (not p.verified, -p.health, p.load))
    return results[:max_peers]


def format_peer_table(peers: List[DiscoveredPeer], token_configured: bool) -> str:
    """Human-readable table for the `gimo discover` CLI output."""
    if not peers:
        hint = "" if token_configured else " (set ORCH_TOKEN to verify peers)"
        return f"No GIMO peers found on the LAN{hint}."

    rows = [
        "  ".join([
            "VERIFIED", "HOST:PORT".ljust(22), "MODE".ljust(10),
            "HEALTH", "LOAD", "RUNTIME".ljust(14), "NAME",
        ]),
        "  ".join([
            "--------", "-" * 22, "-" * 10, "------", "----", "-" * 14, "----",
        ]),
    ]
    for p in peers:
        mark = "YES" if p.verified else "no "
        rows.append(
            "  ".join([
                mark.ljust(8),
                f"{p.host}:{p.port}".ljust(22),
                p.mode.ljust(10),
                f"{p.health:>6}",
                f"{p.load:>4.2f}",
                (p.runtime_version or "-").ljust(14),
                p.name,
            ])
        )
    if not token_configured:
        rows.append("")
        rows.append("hint: export ORCH_TOKEN=<token> to verify announcement signatures.")
    return "\n".join(rows)
