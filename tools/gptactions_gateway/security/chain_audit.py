"""
Audit log con encadenamiento de hashes para el gateway de GPT Actions.

Cada entrada incluye el hash SHA-256 de la entrada anterior,
formando una cadena inviolable. Cualquier modificación o borrado
de entradas rompe la cadena y es detectable mediante verify_chain().

Propiedades:
- Append-only (apertura en modo 'a')
- Thread-safe mediante Lock
- Cada entrada es un JSON en una sola línea
- La integridad de toda la cadena es verificable offline
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("gptactions.audit_chain")

_GENESIS_HASH = "0" * 64  # Sentinel para la primera entrada


class ChainedAuditLog:
    """
    Audit log append-only con cadena de hashes.

    Formato por línea (JSON):
        {
            "seq":          int,       # Número de secuencia
            "ts":           str,       # ISO-8601 UTC
            "event":        str,       # Tipo de evento
            "src_ip":       str,       # IP de origen (hash si paranoia alta)
            "payload_hash": str,       # SHA-256 del cuerpo del request
            "actor_hash":   str,       # SHA-256 del token de auth
            "outcome":      str,       # ALLOWED | DENIED | PENDING | ERROR
            "detail":       str,       # Detalle adicional (sanitizado)
            "prev_hash":    str,       # entry_hash de la entrada anterior
            "entry_hash":   str        # SHA-256 de esta entrada (sin entry_hash)
        }
    """

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Cargamos el estado inicial leyendo la última línea
        self._seq, self._prev_hash = self._bootstrap()

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------

    def _bootstrap(self) -> tuple[int, str]:
        """Lee el log existente y devuelve (último_seq, último_entry_hash)."""
        if not self._path.exists():
            return 0, _GENESIS_HASH
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                return 0, _GENESIS_HASH
            last = json.loads(lines[-1])
            return int(last.get("seq", 0)), last.get("entry_hash", _GENESIS_HASH)
        except Exception as exc:
            logger.warning("chain_audit bootstrap error: %s — reiniciando secuencia", exc)
            return 0, _GENESIS_HASH

    # ------------------------------------------------------------------
    # Hash de entrada
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_entry_hash(entry: dict) -> str:
        """SHA-256 del dict de entrada, excluyendo la clave 'entry_hash'."""
        sans_hash = {k: v for k, v in entry.items() if k != "entry_hash"}
        canonical = json.dumps(sans_hash, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def append(
        self,
        event: str,
        src_ip: str,
        payload_hash: str,
        actor_hash: str,
        outcome: str,
        detail: str,
    ) -> str:
        """
        Añade una entrada a la cadena.

        Devuelve el entry_hash de la nueva entrada (útil para correlación).
        """
        # Sanitizar detail: sin newlines, máx 512 chars
        safe_detail = detail.replace("\n", " ").replace("\r", " ")[:512]

        with self._lock:
            self._seq += 1
            entry: dict = {
                "seq": self._seq,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": event,
                "src_ip": src_ip,
                "payload_hash": payload_hash,
                "actor_hash": actor_hash,
                "outcome": outcome,
                "detail": safe_detail,
                "prev_hash": self._prev_hash,
            }
            entry_hash = self._compute_entry_hash(entry)
            entry["entry_hash"] = entry_hash

            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n")

            self._prev_hash = entry_hash
            return entry_hash

    def verify_chain(self) -> tuple[bool, str]:
        """
        Verifica la integridad de toda la cadena desde la primera entrada.

        Returns:
            (True, "ok message")  si la cadena está íntegra
            (False, "error msg")  si se detecta manipulación
        """
        if not self._path.exists():
            return True, "Log vacío — cadena íntegra (genesis)"
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        except OSError as exc:
            return False, f"No se puede leer el log: {exc}"

        if not lines:
            return True, "Log vacío — cadena íntegra (genesis)"

        prev_hash = _GENESIS_HASH
        for i, raw_line in enumerate(lines, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                return False, f"Línea {i}: JSON inválido (log corrompido)"

            # Verificar enlace con entrada anterior
            stored_prev = entry.get("prev_hash", "")
            if stored_prev != prev_hash:
                return (
                    False,
                    f"Línea {i} (seq={entry.get('seq')}): prev_hash no coincide "
                    f"(esperado={prev_hash[:16]}… encontrado={stored_prev[:16]}…)",
                )

            # Verificar hash de la propia entrada
            stored_hash = entry.get("entry_hash", "")
            computed = self._compute_entry_hash(entry)
            if stored_hash != computed:
                return (
                    False,
                    f"Línea {i} (seq={entry.get('seq')}): entry_hash no coincide "
                    f"(entrada manipulada)",
                )

            prev_hash = stored_hash

        return True, f"Cadena íntegra ({len(lines)} entradas)"

    def tail(self, n: int = 50) -> list[dict]:
        """Devuelve las últimas n entradas (para inspección, sin verificar chain)."""
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            result = []
            for raw in lines[-n:]:
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
            return result
        except OSError:
            return []
