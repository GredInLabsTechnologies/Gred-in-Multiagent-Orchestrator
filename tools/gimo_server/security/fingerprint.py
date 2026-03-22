"""
GIMO Hardware Fingerprint Engine
==================================
Genera un fingerprint multi-señal estable y no-reversible de la máquina actual.

Inspirado en:
  - https://github.com/alphabetanetcom/system-hardware-id-generator
  - https://netlicensing.io/wiki/faq-how-to-generate-machine-fingerprint

Señales usadas (5 en total):
  1. Machine ID del OS (MachineGuid en Windows, /etc/machine-id en Linux, etc.)
  2. MAC address del primer NIC no-virtual
  3. CPU brand string + core count
  4. Disk serial del volumen raíz
  5. OS username (login)

El fingerprint final es SHA-256(señales_concatenadas + SALT).
Si 1-2 señales cambian (ej: nuevo adaptador de red), fuzzy matching con threshold 3/5 (60%).
"""

import hashlib
import logging
import os
import platform
import re
import socket
import subprocess
import uuid

logger = logging.getLogger(__name__)

# Salt fijo embebido — hace el fingerprint no-reversible
# No es secreto (puede estar en el código), solo previene rainbow tables básicas
_FINGERPRINT_SALT = "GIMO-HW-FP-2026-v1"


# ---------------------------------------------------------------------------
# Signal collectors (cada una retorna string o "" si falla)
# ---------------------------------------------------------------------------


def _get_machine_id() -> str:
    """Machine ID del OS. Muy estable — cambia solo si se reinstala el OS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg  # type: ignore[import]

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            return str(value).strip()
        elif system == "Linux":
            path = "/etc/machine-id"
            if os.path.exists(path):
                return open(path).read().strip()
            path = "/var/lib/dbus/machine-id"
            if os.path.exists(path):
                return open(path).read().strip()
        elif system == "Darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformSerialNumber" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        return parts[1].strip().strip('"')
    except Exception as e:
        logger.debug("machine_id collection failed: %s", e)
    return ""


def _get_mac_address() -> str:
    """MAC del primer NIC no-virtual. Moderadamente estable."""
    try:
        # uuid.getnode() devuelve el MAC como entero de 48 bits
        mac_int = uuid.getnode()
        if mac_int == 0:
            return ""
        # Convertir a string hex con separadores
        mac_hex = ":".join(
            ["{:02x}".format((mac_int >> (8 * i)) & 0xFF) for i in range(5, -1, -1)]
        )
        # Filtrar MACs que sean claramente virtuales o inválidas
        # (algunos sistemas reportan loopback como MAC)
        if mac_hex.startswith("00:00:00"):
            return ""
        return mac_hex
    except Exception as e:
        logger.debug("mac_address collection failed: %s", e)
    return ""


def _get_cpu_info() -> str:
    """CPU brand string + número de cores. Muy estable."""
    try:
        cpu_count = str(os.cpu_count() or 0)
        system = platform.system()

        brand = ""
        if system == "Windows":
            import winreg  # type: ignore[import]

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            brand, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
        elif system == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        brand = line.split(":")[1].strip()
                        break
        elif system == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            brand = result.stdout.strip()

        if not brand:
            brand = platform.processor() or "unknown"

        # Normalizar: quitar espacios múltiples, lowercase
        brand = re.sub(r"\s+", " ", brand).strip().lower()
        return f"{brand}:{cpu_count}"
    except Exception as e:
        logger.debug("cpu_info collection failed: %s", e)
    return ""


def _get_disk_serial() -> str:
    """Serial del disco del volumen raíz. Estable, puede cambiar si se reemplaza disco."""
    try:
        system = platform.system()
        if system == "Windows":
            # wmic diskdrive get SerialNumber
            result = subprocess.run(
                ["wmic", "diskdrive", "get", "SerialNumber"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if len(lines) >= 2:
                # Primera línea es cabecera, segunda es el valor
                serial = lines[1].strip()
                if serial and serial != "SerialNumber":
                    return serial
        elif system == "Linux":
            # Intentar varios nombres de disco comunes (SATA, NVMe, virtio, eMMC)
            disk_candidates = ["/dev/sda", "/dev/nvme0n1", "/dev/vda", "/dev/mmcblk0", "/dev/sdb"]
            for disk in disk_candidates:
                try:
                    result = subprocess.run(
                        ["lsblk", "-no", "SERIAL", disk],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    serial = result.stdout.strip()
                    if serial and serial != "":
                        return serial
                except Exception:
                    continue
            # Fallback: leer /sys/class/dmi/id/product_uuid (disponible en la mayoría de VMs/bare-metal)
            try:
                uuid_path = "/sys/class/dmi/id/product_uuid"
                if os.path.exists(uuid_path):
                    val = open(uuid_path).read().strip()
                    if val:
                        return val
            except Exception:
                pass
        elif system == "Darwin":
            result = subprocess.run(
                ["diskutil", "info", "/"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "Disk / Partition UUID" in line or "Volume UUID" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        return parts[1].strip()
    except Exception as e:
        logger.debug("disk_serial collection failed: %s", e)
    return ""


def _get_username() -> str:
    """Login name del usuario actual. Cambia si el usuario renombra su cuenta."""
    try:
        return os.getlogin()
    except Exception:
        pass
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_fingerprint_components() -> dict:
    """
    Retorna cada señal por separado para fuzzy matching.
    Útil para comparar fingerprints cuando alguna señal ha cambiado.
    """
    return {
        "machine_id": _get_machine_id(),
        "mac_address": _get_mac_address(),
        "cpu_info": _get_cpu_info(),
        "disk_serial": _get_disk_serial(),
        "username": _get_username(),
        "platform": platform.system(),
        "hostname": socket.gethostname(),
    }


def generate_fingerprint() -> str:
    """
    Genera el fingerprint SHA-256 de la máquina actual.
    Combina 5 señales + salt para producir un hash estable y no-reversible.

    Returns:
        Hex string de 64 chars (SHA-256).
    """
    components = generate_fingerprint_components()

    # Concatenar todas las señales en un string determinístico
    # Orden fijo para que el hash sea siempre igual con los mismos valores
    signals = "|".join(
        [
            components.get("machine_id", ""),
            components.get("mac_address", ""),
            components.get("cpu_info", ""),
            components.get("disk_serial", ""),
            components.get("username", ""),
        ]
    )

    combined = f"{signals}|{_FINGERPRINT_SALT}"
    fingerprint = hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest()

    logger.debug(
        "Fingerprint generated: %s... (signals: machine_id=%s, mac=%s, cpu=%s, disk=%s, user=%s)",
        fingerprint[:16],
        bool(components.get("machine_id")),
        bool(components.get("mac_address")),
        bool(components.get("cpu_info")),
        bool(components.get("disk_serial")),
        bool(components.get("username")),
    )

    return fingerprint


def compare_fingerprints(
    stored: dict,
    current: dict,
    threshold: float = 0.6,
) -> bool:
    """
    Compara dos conjuntos de componentes de fingerprint.
    Usa fuzzy matching: al menos `threshold` fracción de señales debe coincidir.

    Args:
        stored: dict de componentes del fingerprint guardado
        current: dict de componentes del fingerprint actual
        threshold: fracción mínima de coincidencias (default: 0.6 = 3/5)

    Returns:
        True si los fingerprints se consideran la misma máquina.
    """
    signal_keys = ["machine_id", "mac_address", "cpu_info", "disk_serial", "username"]

    matches = 0
    for key in signal_keys:
        stored_val = stored.get(key, "").strip()
        current_val = current.get(key, "").strip()

        # Si ambos están vacíos, no cuenta como match ni como mismatch
        if not stored_val and not current_val:
            continue

        # Si uno está vacío pero el otro no, es mismatch
        if not stored_val or not current_val:
            continue

        if stored_val == current_val:
            matches += 1

    # Señales con valor en al menos uno de los dos
    comparable = sum(
        1
        for key in signal_keys
        if stored.get(key, "").strip() or current.get(key, "").strip()
    )

    if comparable == 0:
        # No hay señales comparables — forzar online
        return False

    match_ratio = matches / comparable
    is_same = match_ratio >= threshold

    logger.debug(
        "Fingerprint comparison: %d/%d signals match (%.0f%%) — %s",
        matches,
        comparable,
        match_ratio * 100,
        "SAME" if is_same else "DIFFERENT",
    )

    return is_same
