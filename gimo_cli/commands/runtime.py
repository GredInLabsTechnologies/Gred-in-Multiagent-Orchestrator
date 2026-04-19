"""`gimo runtime` — operaciones sobre el bundle Core empaquetado.

Subcomandos:

* ``gimo runtime status``   — muestra versión instalada + provenance del launcher
* ``gimo runtime upgrade``  — baja un bundle desde un peer y lo promueve

Usage::

    gimo runtime status
    gimo runtime upgrade --peer http://192.168.1.50:9325
    gimo runtime upgrade --peer http://host:9325 --allow-downgrade
    gimo runtime upgrade --peer http://host:9325 --json

Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING step 8.
"""
from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from gimo_cli import app, console

runtime_app = typer.Typer(name="runtime", help="Operaciones sobre el bundle Core")
app.add_typer(runtime_app, name="runtime")


def _default_assets_dir() -> Path:
    override = os.environ.get("ORCH_RUNTIME_ASSETS_DIR", "").strip()
    if override:
        return Path(override).resolve()
    # Repo root detectado desde este archivo: gimo_cli/commands/runtime.py
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "runtime-assets"


def _default_target_dir() -> Path:
    override = os.environ.get("ORCH_RUNTIME_DIR", "").strip()
    if override:
        return Path(override).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "runtime"


@runtime_app.command("status")
def runtime_status(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Muestra el estado del bundle local (versión + path + target)."""
    assets_dir = _default_assets_dir()
    manifest_path = assets_dir / "gimo-core-runtime.json"
    target_dir = _default_target_dir()
    marker = target_dir / ".extracted-version"

    info: dict = {
        "assets_dir": str(assets_dir),
        "target_dir": str(target_dir),
        "manifest_present": manifest_path.exists(),
        "extracted_version": None,
        "manifest_version": None,
        "manifest_target": None,
    }
    if manifest_path.exists():
        try:
            from tools.gimo_server.models.runtime import RuntimeManifest
            m = RuntimeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            info["manifest_version"] = m.runtime_version
            info["manifest_target"] = m.target.value
        except Exception as exc:
            info["manifest_error"] = str(exc)
    if marker.exists():
        info["extracted_version"] = marker.read_text(encoding="utf-8").strip()

    if as_json:
        console.print_json(data=info)
        return

    console.print(f"[bold]Assets dir:[/bold]   {info['assets_dir']}")
    console.print(f"[bold]Target dir:[/bold]   {info['target_dir']}")
    if info["manifest_present"]:
        console.print(
            f"[bold]Manifest:[/bold]     version={info['manifest_version']} "
            f"target={info['manifest_target']}"
        )
    else:
        console.print("[yellow]Manifest ausente — no hay bundle publicado localmente.[/yellow]")
    if info["extracted_version"]:
        console.print(f"[bold]Extraído:[/bold]     {info['extracted_version']}")
    else:
        console.print("[dim]No extraído todavía.[/dim]")


@runtime_app.command("upgrade")
def runtime_upgrade(
    peer: str = typer.Option(..., "--peer", "-p", help="Base URL del peer (http://host:port)"),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        help="ORCH_TOKEN del peer (default: env ORCH_TOKEN)",
        envvar="ORCH_TOKEN",
    ),
    allow_downgrade: bool = typer.Option(
        False, "--allow-downgrade", help="Permite bajar de versión"
    ),
    allow_unsigned: bool = typer.Option(
        False,
        "--allow-unsigned",
        help="Omite verificación de firma. NO USAR en producción.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Descarga y promueve un bundle desde un peer del mesh."""
    try:
        from tools.gimo_server.services.runtime_upgrader import (
            RuntimeUpgradeError,
            upgrade_from_peer,
        )
    except ImportError as exc:
        console.print(f"[red]runtime upgrade unavailable: {exc}[/red]")
        raise typer.Exit(1)

    assets_dir = _default_assets_dir()
    target_dir = _default_target_dir()
    peer_token = token if token is not None else os.environ.get("ORCH_TOKEN", "")
    pub_key = os.environ.get("ORCH_RUNTIME_PUBLIC_KEY") or None

    def _progress(written: int, total: Optional[int]) -> None:
        if as_json:
            return
        if total:
            pct = (written / total) * 100 if total else 0.0
            msg = f"\r  {written / (1024 * 1024):.1f} MiB / {total / (1024 * 1024):.1f} MiB ({pct:.0f}%)"
        else:
            msg = f"\r  {written / (1024 * 1024):.1f} MiB"
        sys.stdout.write(msg)
        sys.stdout.flush()

    if not as_json:
        console.print(f"[cyan]→ Descargando runtime desde {peer}[/cyan]")

    try:
        result = upgrade_from_peer(
            peer,
            assets_dir=assets_dir,
            target_dir=target_dir,
            token=peer_token,
            public_key_pem=pub_key,
            allow_unsigned=allow_unsigned,
            allow_downgrade=allow_downgrade,
            on_progress=_progress,
        )
    except RuntimeUpgradeError as exc:
        if not as_json:
            sys.stdout.write("\n")
            sys.stdout.flush()
            console.print(f"[red]Upgrade FALLÓ: {exc}[/red]")
        else:
            console.print_json(data={"status": "error", "error": str(exc)})
        raise typer.Exit(2)

    if not as_json:
        sys.stdout.write("\n")
        sys.stdout.flush()

    payload = {
        "status": "ok",
        "outcome": result.outcome.value,
        "from_version": result.from_version,
        "to_version": result.to_version,
        "bytes_transferred": result.bytes_transferred,
        "runtime_dir": str(result.bootstrap.runtime_dir) if result.bootstrap else None,
        "python_binary": str(result.bootstrap.python_binary) if result.bootstrap else None,
    }
    if as_json:
        console.print_json(data=payload)
        return

    if result.outcome.value == "up_to_date":
        console.print(
            f"[green]✓ Runtime ya está al día (version={result.to_version}).[/green]"
        )
    else:
        verb = "Upgrade" if result.outcome.value == "upgraded" else "Downgrade"
        console.print(
            f"[green]✓ {verb} completo: {result.from_version or '<none>'} → {result.to_version}[/green]"
        )
        if result.bootstrap:
            console.print(f"  Runtime dir: {result.bootstrap.runtime_dir}")
            console.print(f"  Python:      {result.bootstrap.python_binary}")
