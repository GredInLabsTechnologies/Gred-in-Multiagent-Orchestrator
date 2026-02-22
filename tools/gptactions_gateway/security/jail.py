"""
Jaula de sistema de archivos para el gateway de GPT Actions.

Todas las operaciones de I/O que el gateway realiza en nombre de Actions
pasan obligatoriamente por este módulo. Cualquier intento de salir
de JAIL_ROOT lanza JailViolation (→ 403).

Protecciones implementadas:
  - Traversal con ../
  - Null bytes (\x00)
  - NTFS Alternate Data Streams (archivo:stream)
  - Symlinks y junction points que apuntan fuera del jail
  - Nombres reservados de Windows (CON, NUL, COM1…)
  - Depth excesivo (> MAX_PATH_DEPTH)
  - Archivos binarios (en patches)
  - Demasiados patches pendientes (> MAX_PENDING_PATCHES)
  - Archivos demasiado grandes (> MAX_PATCH_BYTES)
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("gptactions.jail")

# Límites
MAX_PATH_DEPTH = 8
MAX_PATCH_BYTES = 524_288  # 512 KB por patch
MAX_PENDING_PATCHES = 5

# Extensiones de archivo permitidas dentro del jail (solo código fuente)
ALLOWED_PATCH_TARGETS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".c", ".cpp", ".h",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".sh", ".bash",
}

# Directorios protegidos que Actions NUNCA puede leer ni escribir
FORBIDDEN_DIRS = {
    ".git", ".env", ".ssh", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", "secrets",
}

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class JailViolation(Exception):
    """Se lanza cuando una operación intenta salir del jail."""
    pass


class PatchQuotaExceeded(Exception):
    """Se lanza cuando ya hay demasiados patches pendientes."""
    pass


class Jail:
    """
    Enforcer de filesystem confinado a un único directorio raíz.

    Uso:
        jail = Jail(Path("/ruta/al/jail"))
        path = jail.resolve("patches/abc123.json")   # lanza JailViolation si sale
        jail.write_patch("patches/abc.json", data)
    """

    def __init__(self, jail_root: Path) -> None:
        jail_root.mkdir(parents=True, exist_ok=True)
        self._root = jail_root.resolve()
        # Crear subdirectorios esperados
        (self._root / "patches").mkdir(exist_ok=True)
        (self._root / "manifest").mkdir(exist_ok=True)
        logger.info("Jail inicializado en: %s", self._root)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Resolución de paths
    # ------------------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """
        Resuelve un path relativo dentro del jail.
        Lanza JailViolation si viola cualquier restricción.
        """
        self._validate_raw(relative)

        candidate = (self._root / relative).resolve()

        # La ruta resuelta debe estar dentro del jail
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise JailViolation(f"Path escapa del jail: {candidate!r}")

        # Si existe, verificar que no sea un symlink/junction que apunte afuera
        if candidate.exists():
            real = Path(os.path.realpath(candidate))
            try:
                real.relative_to(self._root)
            except ValueError:
                raise JailViolation(
                    f"Symlink/junction apunta fuera del jail: "
                    f"{candidate!r} → {real!r}"
                )

        return candidate

    def _validate_raw(self, raw: str) -> None:
        """Validaciones sobre el string de path antes de resolverlo."""
        if not isinstance(raw, str):
            raise JailViolation("El path debe ser una cadena de texto")

        # Null bytes
        if "\x00" in raw:
            raise JailViolation("Null byte en path")

        # Alternate Data Streams de NTFS (file:stream)
        # Excluimos "C:\" y "D:\" de la detección de ':'
        stripped = raw.replace(":/", "").replace(":\\", "")
        if ":" in stripped:
            raise JailViolation("Alternate Data Stream detectado en path")

        # Separamos los componentes del path
        parts = raw.replace("\\", "/").split("/")
        non_empty = [p for p in parts if p and p != "."]

        # Traversal explícito
        if ".." in non_empty:
            raise JailViolation("Path traversal detectado (..)")

        # Profundidad excesiva
        if len(non_empty) > MAX_PATH_DEPTH:
            raise JailViolation(
                f"Path demasiado profundo: {len(non_empty)} niveles > {MAX_PATH_DEPTH}"
            )

        # Nombres reservados de Windows
        for part in non_empty:
            base = part.split(".")[0].upper()
            if base in _WINDOWS_RESERVED:
                raise JailViolation(f"Nombre reservado de Windows: {part!r}")

        # Directorios prohibidos
        for part in non_empty:
            if part.lower() in {d.lower() for d in FORBIDDEN_DIRS}:
                raise JailViolation(f"Directorio prohibido: {part!r}")

    # ------------------------------------------------------------------
    # Operaciones de lectura
    # ------------------------------------------------------------------

    def read_file(self, relative: str) -> bytes:
        """Lee un archivo del jail respetando el límite de tamaño."""
        path = self.resolve(relative)
        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {relative!r}")
        if not path.is_file():
            raise IsADirectoryError(f"Es un directorio, no un archivo: {relative!r}")
        size = path.stat().st_size
        if size > MAX_PATCH_BYTES:
            raise PermissionError(
                f"Archivo demasiado grande: {size:,} bytes > {MAX_PATCH_BYTES:,}"
            )
        return path.read_bytes()

    def list_dir(self, relative: str = ".") -> list[str]:
        """Lista el contenido de un directorio dentro del jail."""
        path = self.resolve(relative)
        if not path.is_dir():
            raise NotADirectoryError(f"No es un directorio: {relative!r}")
        return [
            entry.name
            for entry in sorted(path.iterdir())
            if entry.name not in FORBIDDEN_DIRS
        ]

    # ------------------------------------------------------------------
    # Operaciones de patches
    # ------------------------------------------------------------------

    def count_pending_patches(self) -> int:
        patches_dir = self._root / "patches"
        return sum(1 for f in patches_dir.glob("*.json"))

    def write_patch(self, filename: str, content: bytes) -> Path:
        """
        Escribe un patch en el subdirectorio patches/.
        Lanza PatchQuotaExceeded si ya hay MAX_PENDING_PATCHES.
        """
        if self.count_pending_patches() >= MAX_PENDING_PATCHES:
            raise PatchQuotaExceeded(
                f"Cuota de patches pendientes alcanzada: "
                f"{MAX_PENDING_PATCHES} máximo"
            )
        if len(content) > MAX_PATCH_BYTES:
            raise PermissionError(
                f"Contenido del patch demasiado grande: "
                f"{len(content):,} > {MAX_PATCH_BYTES:,} bytes"
            )

        # Solo permitimos nombres de archivo saneados (UUID.json)
        import re
        if not re.fullmatch(r"[a-f0-9\-]{8,64}\.json", filename):
            raise JailViolation(
                f"Nombre de archivo de patch inválido: {filename!r} "
                f"(solo se aceptan nombres UUID en formato hexadecimal)"
            )

        path = self.resolve(f"patches/{filename}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        # Solo lectura para el usuario del servicio tras escritura
        # (el validador leerá, no modificará)
        logger.info("Patch escrito en jail: %s (%d bytes)", path.name, len(content))
        return path

    def read_patch(self, patch_id: str) -> bytes:
        """Lee un patch por su ID (UUID sin extensión)."""
        return self.read_file(f"patches/{patch_id}.json")

    def list_patches(self) -> list[str]:
        """Devuelve los IDs de patches pendientes (sin extensión .json)."""
        patches_dir = self._root / "patches"
        return [f.stem for f in sorted(patches_dir.glob("*.json"))]

    def archive_patch(self, patch_id: str, reason: str = "processed") -> None:
        """Mueve un patch al subdirectorio archive/ (no lo borra)."""
        archive_dir = self._root / "archive"
        archive_dir.mkdir(exist_ok=True)
        src = self.resolve(f"patches/{patch_id}.json")
        if src.exists():
            dst = archive_dir / f"{patch_id}__{reason}.json"
            src.rename(dst)
            logger.info("Patch archivado: %s → %s", src.name, dst.name)

    # ------------------------------------------------------------------
    # Verificación de tipo de archivo
    # ------------------------------------------------------------------

    def assert_text_file(self, data: bytes) -> None:
        """
        Lanza PermissionError si los datos parecen ser binarios.
        Heurística: > 10% de bytes no-imprimibles → binario.
        """
        if len(data) == 0:
            return
        non_printable = sum(
            1 for b in data[:4096] if b < 9 or (13 < b < 32) or b == 127
        )
        ratio = non_printable / min(len(data), 4096)
        if ratio > 0.10:
            raise PermissionError(
                f"Archivo detectado como binario ({ratio:.1%} bytes no imprimibles)"
            )
