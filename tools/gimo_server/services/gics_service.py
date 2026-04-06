"""
GicsService — GIMO wrapper over the official GICS 1.3.4 Python SDK.

Architecture:
  - Daemon lifecycle is delegated to GICSDaemonSupervisor (official SDK).
  - All IPC/socket/retry/token logic is delegated to GICSClient (official SDK).
  - This class owns GIMO-specific product logic: scoring, trust seeding,
    reliability records. It does NOT duplicate transport concerns.

Compliance: GICS_1_3_4_CLIENT_CONSUMPTION_SCOPE.md — GIMO section.
"""

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import GICS_DAEMON_SCRIPT, GICS_SOCKET_PATH, GICS_TOKEN_PATH, OPS_DATA_DIR
from vendor.gics.clients.python.gics_client import GICSClient, GICSDaemonSupervisor

logger = logging.getLogger("orchestrator.services.gics")

# ── Windows named-pipe convention (matches 1.3.4 daemon defaults) ─────────────
_WINDOWS_PIPE = r"\\.\pipe\gics-daemon"


def _resolve_address() -> str:
    """Canonical IPC address for this platform and GIMO's data layout."""
    if os.name == "nt":
        return _WINDOWS_PIPE
    return str(GICS_SOCKET_PATH)


def _resolve_cli_path() -> Optional[str]:
    """Path to the compiled GICS CLI shipped in vendor/gics."""
    candidate = GICS_DAEMON_SCRIPT
    if candidate and Path(str(candidate)).exists():
        return str(candidate)
    return None


class GicsService:
    """
    Service to manage the GICS Daemon and communicate via the official SDK.

    Public API is kept backward-compatible with all existing GIMO consumers.
    New 1.3.4 primitives (put_many, count_prefix, latest_by_prefix,
    scan_summary, seed_profile, seed_policy) are surfaced alongside the
    existing GIMO-specific scoring helpers.
    """

    def __init__(self) -> None:
        self._address = _resolve_address()
        self._token_path = str(GICS_TOKEN_PATH)
        self._data_path = str(OPS_DATA_DIR / "gics_data")
        self._cli_path = _resolve_cli_path()
        self._token: Optional[str] = None

        # Official SDK objects — created lazily
        self._supervisor: Optional[GICSDaemonSupervisor] = None
        self._client: Optional[GICSClient] = None
        self._health_task: Optional[asyncio.Task] = None
        self._last_alive: bool = False  # Updated by health loop — reflects actual liveness

        # Per-key locks to prevent read-modify-write races in reliability tracking.
        # Threading locks (not asyncio) because the GICS IPC calls are synchronous.
        self._outcome_locks: Dict[str, threading.Lock] = {}
        self._outcome_locks_mutex = threading.Lock()

    def _outcome_lock(self, key: str) -> threading.Lock:
        """Return (creating if needed) the per-key lock for reliability writes."""
        with self._outcome_locks_mutex:
            if key not in self._outcome_locks:
                self._outcome_locks[key] = threading.Lock()
            return self._outcome_locks[key]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_daemon(self) -> None:
        """Start the GICS daemon via the official GICSDaemonSupervisor."""
        if self._supervisor is not None:
            logger.info("GICS daemon supervisor already active.")
            return

        if not self._cli_path:
            logger.error(
                "GICS CLI not found at %s — daemon cannot start.", GICS_DAEMON_SCRIPT
            )
            return

        gics_data_path = Path(self._data_path)
        gics_data_path.mkdir(parents=True, exist_ok=True)

        logger.info("Starting GICS daemon (cli=%s, address=%s) …", self._cli_path, self._address)
        try:
            self._supervisor = GICSDaemonSupervisor(
                cli_path=self._cli_path,
                address=self._address,
                token_path=self._token_path,
                data_path=self._data_path,
            )
            self._supervisor.start(wait=True, timeout=15.0)
            logger.info("GICS daemon ready.")
            self._client = self._make_client()
            self._last_alive = True
        except Exception as exc:
            logger.error("Failed to start GICS daemon: %s", exc)
            self._supervisor = None

    def stop_daemon(self) -> None:
        """Stop the GICS daemon and close client connections."""
        self._last_alive = False
        self.stop_health_check()
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        if self._supervisor:
            try:
                self._supervisor.stop()
                logger.info("GICS daemon stopped.")
            except Exception as exc:
                logger.warning("Error stopping GICS daemon: %s", exc)
            self._supervisor = None

    def _make_client(self) -> GICSClient:
        return GICSClient(
            address=self._address,
            token=self._token,
            token_path=self._token_path,
            max_retries=3,
            retry_delay=0.5,
            request_timeout=5.0,
            pool_size=4,
        )

    @property
    def _rpc(self) -> GICSClient:
        """Lazy access to the official SDK client."""
        if self._client is None:
            self._client = self._make_client()
        return self._client

    # —— Backward-compatible transport shims ————————————————————————————————————————————

    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Legacy shim kept for older tests and callers expecting raw RPC dispatch."""
        return self._rpc._call(method, params or {})

    def _send_with_retry(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> Any:
        """Legacy retry wrapper for transient transport failures."""
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return self.send_command(method, params or {})
            except Exception as exc:
                last_error = exc
                if attempt == max_retries - 1:
                    raise
                time.sleep(retry_delay * (2 ** attempt))
        if last_error:
            raise last_error
        return None

    # ── Health check ──────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                await self._rpc.aping()
                self._last_alive = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_alive = False
                logger.warning("GICS health check error: %s", exc)

    def start_health_check(self) -> None:
        if self._health_task and not self._health_task.done():
            return
        try:
            self._health_task = asyncio.create_task(self._health_loop())
        except RuntimeError:
            self._health_task = None

    def stop_health_check(self) -> None:
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        self._health_task = None

    # ── Core CRUD (SDK delegates) ──────────────────────────────────────────────

    def put(self, key: str, fields: Dict[str, Any]) -> Any:
        try:
            return self._rpc.put(key, fields)
        except Exception as exc:
            logger.error("GICS put(%s) failed: %s", key, exc)
            return None

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            return self._rpc.get(key)
        except Exception as exc:
            logger.error("GICS get(%s) failed: %s", key, exc)
            return None

    def delete(self, key: str) -> bool:
        try:
            return self._rpc.delete(key)
        except Exception as exc:
            logger.error("GICS delete(%s) failed: %s", key, exc)
            return False

    def scan(self, prefix: str = "", include_fields: bool = True) -> List[Dict[str, Any]]:
        """Backward-compatible scan wrapper (include_fields maps to SDK default)."""
        try:
            return self._rpc.scan(prefix=prefix)
        except Exception as exc:
            logger.error("GICS scan(prefix=%r) failed: %s", prefix, exc)
            return []

    def flush(self) -> Any:
        """No-op shim kept for backward compat — daemon auto-flushes."""
        pass

    # ── 1.3.4 bulk & summary primitives ──────────────────────────────────────

    def put_many(
        self,
        records: List[Dict[str, Any]],
        atomic: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """
        Atomic bulk write with optional idempotency key.
        Use instead of repeated put() loops for logical batches.
        """
        try:
            return self._rpc.put_many(records, atomic=atomic, idempotency_key=idempotency_key)
        except Exception as exc:
            logger.error("GICS put_many failed: %s", exc)
            return None

    def count_prefix(self, prefix: str = "") -> Any:
        """Count entries under a key prefix (O(1) vs full scan)."""
        try:
            return self._rpc.count_prefix(prefix=prefix)
        except Exception as exc:
            logger.error("GICS count_prefix(%r) failed: %s", prefix, exc)
            return None

    def latest_by_prefix(self, prefix: str = "") -> Any:
        """Fetch the most recent entry under a key prefix."""
        try:
            return self._rpc.latest_by_prefix(prefix=prefix)
        except Exception as exc:
            logger.error("GICS latest_by_prefix(%r) failed: %s", prefix, exc)
            return None

    def scan_summary(self, prefix: str = "") -> Any:
        """Summary metadata for a prefix (count, range, size) without full payload."""
        try:
            return self._rpc.scan_summary(prefix=prefix)
        except Exception as exc:
            logger.error("GICS scan_summary(%r) failed: %s", prefix, exc)
            return None

    # ── 1.3.4 inference seed APIs ─────────────────────────────────────────────

    def seed_profile(self, scope: str, **kwargs: Any) -> Any:
        """Seed an inference profile prior for a given scope."""
        try:
            return self._rpc.seed_profile(scope=scope, **kwargs)
        except Exception as exc:
            logger.error("GICS seed_profile(%r) failed: %s", scope, exc)
            return None

    def seed_policy(self, domain: str, scope: str, **kwargs: Any) -> Any:
        """Seed an inference policy prior for a domain/scope pair."""
        try:
            return self._rpc.seed_policy(domain=domain, scope=scope, **kwargs)
        except Exception as exc:
            logger.error("GICS seed_policy(%r, %r) failed: %s", domain, scope, exc)
            return None

    # ── GIMO-specific product logic (model scoring / reliability) ─────────────
    # GIMO-specific domain logic lives here, not in GICS itself.

    @staticmethod
    def _model_key(provider_type: str, model_id: str) -> str:
        p = str(provider_type or "unknown").strip().lower().replace(" ", "_")
        m = str(model_id or "unknown").strip().lower().replace(" ", "_")
        return f"ops:model_score:{p}:{m}"

    def seed_model_prior(
        self,
        *,
        provider_type: str,
        model_id: str,
        prior_scores: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Seed initial model priors (phase-1 catalog metadata → GICS)."""
        key = self._model_key(provider_type, model_id)
        with self._outcome_lock(key):
            return self._seed_model_prior_locked(
                key=key, provider_type=provider_type, model_id=model_id,
                prior_scores=prior_scores, metadata=metadata,
            )

    def _seed_model_prior_locked(
        self,
        *,
        key: str,
        provider_type: str,
        model_id: str,
        prior_scores: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inner implementation — must be called with _outcome_lock(key) held."""
        existing = self.get(key)
        fields = dict((existing or {}).get("fields") or {})
        priors = dict(prior_scores or {})
        avg_prior = (
            sum(float(v) for v in priors.values()) / max(1, len(priors))
            if priors
            else float(fields.get("score", 0.5) or 0.5)
        )

        merged = {
            "provider_type": provider_type,
            "model_id": model_id,
            "score": float(fields.get("score", avg_prior) or avg_prior),
            "priors": priors,
            "samples": int(fields.get("samples", 0) or 0),
            "successes": int(fields.get("successes", 0) or 0),
            "failures": int(fields.get("failures", 0) or 0),
            "failure_streak": int(fields.get("failure_streak", 0) or 0),
            "avg_latency_ms": float(fields.get("avg_latency_ms", 0.0) or 0.0),
            "avg_cost_usd": float(fields.get("avg_cost_usd", 0.0) or 0.0),
            "anomaly": bool(fields.get("anomaly", False)),
            "metadata": dict(metadata or fields.get("metadata") or {}),
            "updated_at": int(time.time()),
        }
        self.put(key, merged)
        return merged

    def record_model_outcome(
        self,
        *,
        provider_type: str,
        model_id: str,
        success: bool,
        latency_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
        task_type: str = "general",
    ) -> Dict[str, Any]:
        """Register post-task evidence and update reliability score.

        Thread-safe: uses a per-key lock to prevent concurrent read-modify-write
        races when multiple runs finish simultaneously for the same model.
        """
        key = self._model_key(provider_type, model_id)
        with self._outcome_lock(key):
            existing = self.get(key)
            fields = dict((existing or {}).get("fields") or {})

            samples = int(fields.get("samples", 0) or 0) + 1
            successes = int(fields.get("successes", 0) or 0) + (1 if success else 0)
            failures = int(fields.get("failures", 0) or 0) + (0 if success else 1)
            failure_streak = 0 if success else int(fields.get("failure_streak", 0) or 0) + 1

            prev_latency = float(fields.get("avg_latency_ms", 0.0) or 0.0)
            prev_cost = float(fields.get("avg_cost_usd", 0.0) or 0.0)
            new_latency = float(latency_ms or 0.0)
            new_cost = float(cost_usd or 0.0)
            avg_latency = ((prev_latency * (samples - 1)) + new_latency) / max(1, samples)
            avg_cost = ((prev_cost * (samples - 1)) + new_cost) / max(1, samples)

            success_rate = successes / max(1, samples)
            prior_score = float(fields.get("score", 0.5) or 0.5)
            blended_score = max(0.0, min(1.0, (prior_score * 0.2) + (success_rate * 0.8)))
            anomaly = failure_streak >= 3

            outcome = {
                "provider_type": provider_type,
                "model_id": model_id,
                "task_type": task_type,
                "score": blended_score,
                "samples": samples,
                "successes": successes,
                "failures": failures,
                "failure_streak": failure_streak,
                "avg_latency_ms": avg_latency,
                "avg_cost_usd": avg_cost,
                "anomaly": anomaly,
                "updated_at": int(time.time()),
            }
            self.put(key, {**fields, **outcome})
            return {**fields, **outcome}

    def get_model_reliability(
        self, *, provider_type: str, model_id: str
    ) -> Optional[Dict[str, Any]]:
        key = self._model_key(provider_type, model_id)
        result = self.get(key)
        if not result:
            return None
        return dict(result.get("fields") or {})
