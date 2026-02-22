"""
Sincronizador de rangos de IPs de egress de ChatGPT Actions.

Descarga los rangos de IP publicados por OpenAI y actualiza el archivo
de allowlist local. Debe ejecutarse:
  - Durante el setup inicial
  - Como tarea programada (ej: cron diario)
  - Automáticamente si el gateway detecta que el allowlist está obsoleto

Fuentes de IPs de OpenAI (verificar actualización periódica):
  - https://openai.com/gptbot-ranges.txt  (GPTBot web crawler)
  - Para ChatGPT Actions, OpenAI publica los rangos en su documentación oficial.
    Si la URL cambia, actualiza OPENAI_IPS_URL abajo.

Uso:
    python scripts/setup/sync_openai_ips.py
    python scripts/setup/sync_openai_ips.py --output /ruta/custom/openai_ips.json
    python scripts/setup/sync_openai_ips.py --add-cidr 1.2.3.0/24  # Para testing
    python scripts/setup/sync_openai_ips.py --verify                 # Solo verificar estado
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# ------------------------------------------------------------------
# Rangos de IPs publicados por OpenAI para ChatGPT Actions
# Fuente oficial: https://openai.com/chatgpt/api/
# ACTUALIZAR si cambia la URL o los rangos
# ------------------------------------------------------------------

# URL de los rangos de IPs de OpenAI para GPTBot / ChatGPT Actions
# Nota: OpenAI puede cambiar esta URL — verificar periódicamente
OPENAI_IPS_URL = "https://openai.com/gptbot-ranges.txt"

# Rangos conocidos adicionales de OpenAI (fallback estático si la URL falla)
# Fuente: Documentación de OpenAI (febrero 2026)
# ⚠️ ACTUALIZAR MANUALMENTE si OpenAI añade nuevos rangos
FALLBACK_CIDRS: list[str] = [
    # Microsoft Azure (donde corre ChatGPT) — rangos principales
    "13.64.0.0/11",
    "13.96.0.0/13",
    "13.104.0.0/14",
    "20.0.0.0/8",
    "40.64.0.0/10",
    "52.224.0.0/11",
    # OpenAI directos (publicados)
    "23.102.140.112/28",
    "13.66.11.96/28",
    "104.210.133.240/28",
    "70.37.57.208/28",
    "52.239.170.144/28",
    "52.162.100.96/28",
    "40.84.220.192/28",
    "52.230.222.128/28",
]

# Archivo de salida por defecto
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
DEFAULT_OUTPUT = _REPO_ROOT / "tools" / "gptactions_gateway" / "openai_ips.json"

# Tiempo máximo de espera para descarga
DOWNLOAD_TIMEOUT = 15  # segundos


def _parse_ips_txt(content: str) -> list[str]:
    """
    Parsea el formato de texto de rangos de IPs de OpenAI.
    Acepta líneas con un CIDR por línea, ignorando comentarios (#).
    """
    cidrs = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            # Validar que es un CIDR válido
            ipaddress.ip_network(line, strict=False)
            cidrs.append(line)
        except ValueError:
            pass
    return cidrs


def download_openai_ips() -> tuple[list[str], str, bool]:
    """
    Intenta descargar los rangos de IP de OpenAI.

    Returns:
        (cidrs, source_description, from_fallback)
    """
    try:
        req = urllib.request.Request(
            OPENAI_IPS_URL,
            headers={"User-Agent": "gimo-gptactions-sync/1.0"},
        )
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as response:
            content = response.read().decode("utf-8", errors="replace")
        cidrs = _parse_ips_txt(content)
        if cidrs:
            return cidrs, OPENAI_IPS_URL, False
        print(f"⚠️  La URL {OPENAI_IPS_URL} devolvió contenido sin CIDRs válidos. Usando fallback.")
    except urllib.error.URLError as exc:
        print(f"⚠️  No se pudo descargar {OPENAI_IPS_URL}: {exc}")
    except Exception as exc:
        print(f"⚠️  Error al descargar IPs de OpenAI: {exc}")

    print(f"   Usando fallback estático ({len(FALLBACK_CIDRS)} CIDRs).")
    print("   ⚠️  RECOMENDACIÓN: Verifica y actualiza FALLBACK_CIDRS manualmente.")
    return FALLBACK_CIDRS, "fallback-static", True


def sync(
    output_path: Path = DEFAULT_OUTPUT,
    extra_cidrs: list[str] | None = None,
    force: bool = False,
) -> bool:
    """
    Descarga y guarda el allowlist de IPs.

    Args:
        output_path: Donde guardar el JSON
        extra_cidrs: CIDRs adicionales (ej: tu gateway corporativo)
        force:       Sobreescribir aunque el archivo sea reciente

    Returns:
        True si la sincronización fue exitosa
    """
    # Verificar si necesitamos actualizar
    if not force and output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            fetched_at = existing.get("fetched_at_epoch", 0)
            age_hours = (time.time() - float(fetched_at)) / 3600
            if age_hours < 12:
                print(f"✓ Allowlist actualizado hace {age_hours:.1f}h — no se requiere actualización.")
                print(f"  (Usa --force para forzar actualización)")
                return True
        except Exception:
            pass

    cidrs, source, from_fallback = download_openai_ips()

    if extra_cidrs:
        valid_extra = []
        for cidr in extra_cidrs:
            try:
                ipaddress.ip_network(cidr, strict=False)
                valid_extra.append(cidr)
            except ValueError:
                print(f"  ⚠️  CIDR extra inválido (ignorado): {cidr!r}")
        cidrs = list(set(cidrs + valid_extra))
        print(f"  + {len(valid_extra)} CIDRs adicionales añadidos")

    # Eliminar duplicados y ordenar
    unique_cidrs = sorted(set(cidrs))

    now = time.time()
    content_hash = hashlib.sha256("\n".join(unique_cidrs).encode()).hexdigest()

    allowlist = {
        "fetched_at": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_epoch": now,
        "source_url": source,
        "from_fallback": from_fallback,
        "content_hash": content_hash,
        "cidr_count": len(unique_cidrs),
        "cidrs": unique_cidrs,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(allowlist, indent=2, ensure_ascii=True), encoding="utf-8")

    status = "⚠️  FALLBACK" if from_fallback else "✓"
    print(f"\n{status} Allowlist guardado: {output_path}")
    print(f"   CIDRs: {len(unique_cidrs)}")
    print(f"   Fuente: {source}")
    print(f"   Hash: {content_hash[:16]}…")

    if from_fallback:
        print("\n⚠️  IMPORTANTE: Se usó el fallback estático.")
        print("   Verifica manualmente en https://openai.com/chatgpt/api/ que los")
        print("   rangos son correctos y actualiza FALLBACK_CIDRS si es necesario.")

    return True


def verify(output_path: Path = DEFAULT_OUTPUT) -> None:
    """Muestra el estado actual del allowlist."""
    if not output_path.exists():
        print(f"✗ Archivo no encontrado: {output_path}")
        print("  Ejecuta: python scripts/setup/sync_openai_ips.py")
        return

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"✗ Error al leer allowlist: {exc}")
        return

    age = time.time() - float(data.get("fetched_at_epoch", 0))
    age_str = f"{age/3600:.1f}h" if age < 86400 else f"{age/86400:.1f}d"

    stale = age > 43200  # 12h
    status = "⚠️  OBSOLETO" if stale else "✓"

    print(f"\n{status} Estado del allowlist de IPs")
    print(f"   Archivo:       {output_path}")
    print(f"   CIDRs:         {data.get('cidr_count', '?')}")
    print(f"   Actualizado:   {data.get('fetched_at', '?')} (hace {age_str})")
    print(f"   Fuente:        {data.get('source_url', '?')}")
    print(f"   Fallback:      {data.get('from_fallback', False)}")
    print(f"   Hash:          {data.get('content_hash', '?')[:16]}…")

    if stale:
        print("\n   ⚠️  El allowlist tiene más de 12h — ejecuta sync para actualizarlo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sincronizar rangos de IPs de GPT Actions con OpenAI"
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Ruta de salida del JSON (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--add-cidr",
        action="append",
        dest="extra_cidrs",
        metavar="CIDR",
        help="Añadir un CIDR adicional (puede usarse varias veces)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forzar actualización aunque el archivo sea reciente",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Solo verificar el estado actual, sin actualizar",
    )

    args = parser.parse_args()
    output = Path(args.output)

    if args.verify:
        verify(output)
        sys.exit(0)

    success = sync(
        output_path=output,
        extra_cidrs=args.extra_cidrs,
        force=args.force,
    )
    sys.exit(0 if success else 1)
