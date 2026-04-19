"""`gimo discover` — LAN mDNS auto-discovery of GIMO Core peers (rev 2 Cambio 10).

Browses the LAN for ``_gimo._tcp.local.`` services advertised by a Core running
in server mode. Signature verification uses ``ORCH_TOKEN`` when available — any
peer whose HMAC does not match is shown as unverified and must be connected to
manually, never auto-adopted.

Usage::

    gimo discover                    # 3-second scan, verified peers first
    gimo discover --timeout 8        # longer scan for noisy networks
    gimo discover --json             # emit machine-readable output
"""

from __future__ import annotations

import json
import os
from typing import Optional

import typer

from gimo_cli import app, console


@app.command("discover")
def discover_cmd(
    timeout: float = typer.Option(3.0, "--timeout", "-t", help="Scan duration in seconds"),
    max_peers: int = typer.Option(16, "--max", help="Max peers to return"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        help="Override ORCH_TOKEN for HMAC verification (read from env by default)",
        envvar="ORCH_TOKEN",
    ),
) -> None:
    """Scan the LAN for GIMO Core peers advertised via mDNS."""
    try:
        from tools.gimo_server.services.mesh.mdns_discovery import (
            discover_peers,
            format_peer_table,
        )
    except ImportError as exc:
        console.print(f"[red]discover unavailable: {exc}[/red]")
        raise typer.Exit(1)

    token_value = token if token is not None else os.environ.get("ORCH_TOKEN", "")
    peers = discover_peers(token=token_value, timeout_seconds=timeout, max_peers=max_peers)

    if as_json:
        payload = [
            {
                "name": p.name,
                "host": p.host,
                "port": p.port,
                "url": p.url,
                "mode": p.mode,
                "health": p.health,
                "load": p.load,
                "version": p.version,
                "runtime_version": p.runtime_version,
                "verified": p.verified,
            }
            for p in peers
        ]
        console.print_json(data=payload)
        return

    console.print(format_peer_table(peers, token_configured=bool(token_value)))
