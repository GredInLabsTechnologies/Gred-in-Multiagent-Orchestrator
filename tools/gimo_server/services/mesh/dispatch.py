"""Intelligent dispatch — routes sub-tasks to mesh devices.

Combines GICS patterns, device capacity, thermal state, health score,
and thermal-predictive pre-checks for optimal device selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...models.mesh import DeviceMode, MeshDeviceInfo, TaskFingerprint
from ..gics_service import GicsService
from . import observability as _mesh_obs
from .model_recommendation import FitLevel, score_model
from .pattern_matcher import PatternMatcher
from .registry import MeshRegistry
from .telemetry import TelemetryService

logger = logging.getLogger("orchestrator.mesh.dispatch")


@dataclass
class DispatchDecision:
    """Result of dispatch routing."""
    device_id: str = ""
    model_id: str = ""
    reason: str = ""
    fallback_to_local: bool = False
    thermal_headroom_ok: bool = True
    health_score: float = 100.0
    duty_cycle_remaining_min: float = 0.0
    inference_endpoint: str = ""
    # BUGS_LATENTES §H6 — populated when preferred_model_meta is provided.
    # Values: "optimal" | "comfortable" | "tight" | "overload" | "" (not evaluated)
    model_fit_level: str = ""


# BUGS_LATENTES §H6 — bonus por fit. Ordinal, derivado del FitLevel.
# overload = hard-exclude (el device no puede correr el modelo) → fuerte
# penalty que solo se contrabalancea si todos los demás también overload.
_FIT_SCORE_BONUS: Dict[FitLevel, float] = {
    FitLevel.optimal: 10.0,
    FitLevel.comfortable: 5.0,
    FitLevel.tight: -5.0,
    FitLevel.overload: -30.0,
}


# BUGS_LATENTES §H10 — thermal thresholds tunables.
# Previamente hardcoded en dispatch.py líneas 188-195. Defaults preservan el
# comportamiento histórico; custom se pasa en constructor o env vars.
# Env var nombres siguen convención ORCH_DISPATCH_*.
@dataclass
class ThermalThresholds:
    """Umbrales thermal para el dispatch thermal-predictive pre-check.

    BUGS_LATENTES §H10. Los valores default son idénticos a los hardcoded
    pre-fix. Pueden overridearse en construcción del ``DispatchService`` o
    via env vars para calibración per-device class en el futuro.
    """
    cpu_hot_c: float = 65.0
    gpu_hot_c: float = 70.0
    battery_hot_c: float = 35.0

    @classmethod
    def from_env(cls) -> "ThermalThresholds":
        """Construye desde env vars con fallback al default."""
        import os

        def _get_float(key: str, default: float) -> float:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                logger.warning(
                    "invalid %s=%r — using default %.1f", key, raw, default
                )
                return default

        return cls(
            cpu_hot_c=_get_float("ORCH_DISPATCH_CPU_HOT_C", 65.0),
            gpu_hot_c=_get_float("ORCH_DISPATCH_GPU_HOT_C", 70.0),
            battery_hot_c=_get_float("ORCH_DISPATCH_BATTERY_HOT_C", 35.0),
        )


class DispatchService:
    """Routes sub-tasks to optimal mesh devices."""

    def __init__(
        self,
        registry: MeshRegistry,
        gics: Optional[GicsService] = None,
        host_device_id: Optional[str] = None,
        thermal_thresholds: Optional["ThermalThresholds"] = None,
    ) -> None:
        self._registry = registry
        self._gics = gics
        self._matcher = PatternMatcher(gics) if gics else None
        self._telemetry = TelemetryService()
        # rev 2 Cambio 2 — id of the local bootstrapped host so the scorer can
        # apply a dynamic self-penalty when the local Core is also serving.
        self._host_device_id = host_device_id
        # BUGS_LATENTES §H10 — thresholds tunables (default = histórico).
        self._thermal_thresholds = thermal_thresholds or ThermalThresholds.from_env()

    def dispatch(
        self,
        fingerprint: TaskFingerprint,
        mesh_enabled: bool,
        preferred_model: str = "",
        preferred_model_meta: Optional[Dict[str, Any]] = None,
        task_id: str = "",
    ) -> DispatchDecision:
        """Select the best device for a task. Emits observability span once.

        Args:
            preferred_model_meta: BUGS_LATENTES §H6. Si se provee dict con
                ``params_str``, ``quant_str``, ``size_bytes`` + opcional
                ``model_id``, ``_score_devices`` evalúa fit per (device, model)
                via ModelRecommendationEngine y ajusta el score con un bonus
                por FitLevel. Sin este kwarg, el scoring solo usa heurísticas
                hardware básicas (comportamiento pre-fix).
            task_id: BUGS_LATENTES §H9. Task identifier para el audit log.
                Si se provee, el dispatch decision queda persistido en
                ``audit.jsonl`` bajo category="dispatch" — permite reconstruir
                "por qué esta task fue a este device" después del hecho.
        """
        decision = self._decide(
            fingerprint, mesh_enabled, preferred_model, preferred_model_meta
        )
        _mesh_obs.emit_dispatch(
            device_id=decision.device_id,
            reason=decision.reason,
            fallback_to_local=decision.fallback_to_local,
            health_score=decision.health_score,
            action_class=fingerprint.action_class,
        )
        # BUGS_LATENTES §H9: persist dispatch decision to audit log.
        # Safe: excepciones del audit no tumban dispatch (best-effort).
        self._audit_dispatch(fingerprint, decision, task_id)
        return decision

    def _audit_dispatch(
        self,
        fingerprint: TaskFingerprint,
        decision: DispatchDecision,
        task_id: str,
    ) -> None:
        """Append dispatch outcome a audit.jsonl. BUGS_LATENTES §H9.

        No-op si MeshAuditService falla al inicializarse (p.ej. entornos de
        test sin OPS_DATA_DIR escribible). Si el servicio responde pero el
        record() raise, se loguea DEBUG y continúa.
        """
        try:
            from .audit import MeshAuditService
            audit = MeshAuditService()
            audit.record(
                category="dispatch",
                action="routed" if not decision.fallback_to_local else "fallback_to_local",
                device_id=decision.device_id,
                task_id=task_id,
                details={
                    "action_class": fingerprint.action_class,
                    "model_id": decision.model_id,
                    "reason": decision.reason,
                    "health_score": decision.health_score,
                    "fallback_to_local": decision.fallback_to_local,
                    "thermal_headroom_ok": decision.thermal_headroom_ok,
                    "model_fit_level": decision.model_fit_level,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("dispatch audit write failed (non-critical): %s", exc)

    def _decide(
        self,
        fingerprint: TaskFingerprint,
        mesh_enabled: bool,
        preferred_model: str = "",
        preferred_model_meta: Optional[Dict[str, Any]] = None,
    ) -> DispatchDecision:
        """Pipeline:
        1. Get eligible devices
        2. Filter by capacity (model params)
        3. Thermal-predictive pre-check
        4. Score by health + GICS pattern match
        5. Select best device + model via Thompson Sampling
        6. Fallback to local if no eligible device
        """
        if not mesh_enabled:
            return DispatchDecision(
                fallback_to_local=True,
                reason="Mesh disabled",
            )

        eligible = self._registry.get_eligible_devices(mesh_enabled)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="No eligible mesh devices",
            )

        # Filter by capacity if fingerprint specifies context requirements
        if fingerprint.requires_context_kb > 0:
            eligible = [
                d for d in eligible
                if d.max_model_params_b > 0  # Has capacity info
            ]

        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="No devices with sufficient capacity",
            )

        # Staleness filter: reject devices with no recent heartbeat
        eligible = self._filter_stale_heartbeats(eligible)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="All eligible devices have stale heartbeats",
            )

        # Thermal-predictive pre-check: filter out devices that are close to throttle
        eligible = self._filter_thermal_headroom(eligible)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="All eligible devices near thermal limit",
                thermal_headroom_ok=False,
            )

        # Score devices by health + thermal profile + (optional) model fit
        scored = self._score_devices(eligible, preferred_model_meta)

        # Select best device
        best = scored[0]
        device = best["device"]

        # Model selection via Thompson Sampling
        model_id = preferred_model
        if not model_id and self._matcher and device.model_loaded:
            available_models = self._get_available_models(eligible)
            if available_models:
                model_id = self._matcher.select_model(fingerprint, available_models)

        if not model_id and device.model_loaded:
            model_id = device.model_loaded

        # BUGS_LATENTES §H6: surface fit level en el reason cuando esté presente.
        fit_suffix = ""
        if best.get("fit_level"):
            fit_suffix = f" fit={best['fit_level']}"

        return DispatchDecision(
            device_id=device.device_id,
            model_id=model_id,
            reason=f"Best score: {best['score']:.2f} (health={best['health']:.0f}){fit_suffix}",
            thermal_headroom_ok=True,
            health_score=best["health"],
            duty_cycle_remaining_min=best.get("duty_remaining", 0.0),
            inference_endpoint=device.inference_endpoint,
            model_fit_level=best.get("fit_level", ""),
        )

    @staticmethod
    def _filter_stale_heartbeats(
        devices: List[MeshDeviceInfo], max_age_seconds: float = 120.0
    ) -> List[MeshDeviceInfo]:
        """Reject devices whose last heartbeat is too old."""
        now = datetime.now(timezone.utc)
        fresh: List[MeshDeviceInfo] = []
        for d in devices:
            if d.last_heartbeat is None:
                logger.debug("Skipping %s: no heartbeat recorded", d.device_id)
                continue
            age = (now - d.last_heartbeat).total_seconds()
            if age > max_age_seconds:
                logger.debug("Skipping %s: heartbeat stale (%.0fs)", d.device_id, age)
                continue
            fresh.append(d)
        return fresh

    def _filter_thermal_headroom(
        self, devices: List[MeshDeviceInfo]
    ) -> List[MeshDeviceInfo]:
        """Thermal-predictive pre-check: reject devices that are already warm.

        Novel approach — no competitor does this. Check headroom BEFORE dispatch.

        BUGS_LATENTES §H10: thresholds ahora tunables via ``ThermalThresholds``
        inyectado en el constructor o env vars ``ORCH_DISPATCH_CPU_HOT_C`` /
        ``ORCH_DISPATCH_GPU_HOT_C`` / ``ORCH_DISPATCH_BATTERY_HOT_C``. Defaults
        preservan el comportamiento histórico (65/70/35 °C).
        """
        t = self._thermal_thresholds
        safe: List[MeshDeviceInfo] = []
        for d in devices:
            # Skip if already throttled
            if d.thermal_throttled:
                logger.debug("Skipping %s: already throttled", d.device_id)
                continue

            cpu_hot = d.cpu_temp_c > 0 and d.cpu_temp_c > t.cpu_hot_c
            gpu_hot = d.gpu_temp_c > 0 and d.gpu_temp_c > t.gpu_hot_c
            bat_hot = d.battery_temp_c > 0 and d.battery_temp_c > t.battery_hot_c

            if cpu_hot and gpu_hot:
                logger.debug("Skipping %s: CPU+GPU too warm (%.1f/%.1f)", d.device_id, d.cpu_temp_c, d.gpu_temp_c)
                continue
            if bat_hot and (cpu_hot or gpu_hot):
                logger.debug("Skipping %s: battery+compute too warm", d.device_id)
                continue

            safe.append(d)

        return safe

    def _score_devices(
        self,
        devices: List[MeshDeviceInfo],
        model_fit_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Score devices by health, thermal state, and resource availability.

        Args:
            model_fit_meta: BUGS_LATENTES §H6. Si se provee dict con params_str,
                quant_str, size_bytes (+ opcional model_id), este scoring añade
                el FitLevel bonus de ModelRecommendationEngine para cada device.
                Devices que no puedan correr el modelo pedido reciben penalty
                fuerte (-30 por overload); devices óptimos +10.
        """
        scored: List[Dict[str, Any]] = []

        for d in devices:
            profile = self._telemetry.get_profile(d.device_id)
            health = profile.health_score
            duty_remaining = 0.0

            if profile.recommended_duty_cycle_min > 0:
                # Estimate remaining duty from thermal profile
                duty_remaining = profile.recommended_duty_cycle_min

            # Composite score: health (0-100) + resource availability bonus
            score = health
            # Bonus for low CPU/RAM usage
            if d.cpu_percent < 50:
                score += 10
            if d.ram_percent < 70:
                score += 5
            # Bonus for battery (if on battery, prefer charged devices)
            if d.battery_percent > 50:
                score += 5
            elif d.battery_percent > 0 and d.battery_percent < 20:
                score -= 10  # Penalty for low battery

            # BUGS_LATENTES §H6: ModelRecommendationEngine fit bonus
            # Previamente el engine solo se consumía por un endpoint UI; ahora
            # contribuye al scoring de dispatch. Sin model_fit_meta, comportamiento
            # idéntico al pre-fix (scoring solo por heurísticas hardware).
            fit_level_value = ""
            if model_fit_meta:
                fit_level = self._compute_model_fit(d, model_fit_meta)
                if fit_level is not None:
                    fit_level_value = fit_level.value
                    score += _FIT_SCORE_BONUS.get(fit_level, 0.0)

            # rev 2 Cambio 2 — dynamic self-penalty when the local Core is also a
            # server-mode mesh peer. Prefer offloading to other peers so the host
            # stays responsive for orchestration, but only when the host is
            # actually stressed. Thermal lockout is already filtered upstream, so
            # the ladder only weighs the grey zones.
            if (
                self._host_device_id
                and d.device_id == self._host_device_id
                and d.device_mode == DeviceMode.server
            ):
                headroom_cpu_ok = 0 < d.cpu_temp_c < 50
                headroom_ram_ok = d.ram_percent < 60
                if headroom_cpu_ok and headroom_ram_ok:
                    self_penalty = -5
                else:
                    self_penalty = -10
                # Low-battery-on-mains is the one condition we always want to
                # push hard against: a laptop on its last 30% must not soak more
                # load unless it is charging.
                if (
                    0 < d.battery_percent < 30
                    and not getattr(d, "battery_charging", False)
                ):
                    self_penalty -= 20
                score += self_penalty

            scored.append({
                "device": d,
                "score": score,
                "health": health,
                "duty_remaining": duty_remaining,
                "fit_level": fit_level_value,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _compute_model_fit(
        self, device: MeshDeviceInfo, model_meta: Dict[str, Any]
    ) -> Optional[FitLevel]:
        """Delegate a (device, model) fit evaluation to ModelRecommendationEngine.

        BUGS_LATENTES §H6. Extrae metadata del device (soc_model, capabilities)
        y del modelo (params, quant, size) y llama a ``score_model()``. Devuelve
        FitLevel o None si falta data crítica (ej. device sin capabilities).

        Safe: cualquier excepción se swallow y devuelve None — el dispatch no
        debe fallar porque el recommendation engine tenga un edge case.
        """
        try:
            caps = device.capabilities
            ram_total_mb = caps.ram_total_mb if caps else 0
            storage_free_mb = caps.storage_free_mb if caps else 0
            cpu_cores = caps.cpu_cores if caps else 4
            has_gpu = caps.has_gpu_compute if caps else False

            if ram_total_mb <= 0:
                # Sin capacidad conocida no podemos estimar fit fiable.
                return None

            rec = score_model(
                model_id=str(model_meta.get("model_id", "")),
                params_str=str(model_meta.get("params_str", "")),
                quant_str=str(model_meta.get("quant_str", "q4_k_m")),
                size_bytes=int(model_meta.get("size_bytes", 0) or 0),
                ram_total_mb=int(ram_total_mb),
                storage_free_mb=int(storage_free_mb),
                cpu_cores=int(cpu_cores or 4),
                soc_model=device.soc_model or "",
                has_gpu_compute=bool(has_gpu),
            )
            return rec.fit_level
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "model fit computation failed for device=%s model_meta=%s: %s",
                device.device_id, model_meta, exc,
            )
            return None

    @staticmethod
    def _get_available_models(devices: List[MeshDeviceInfo]) -> List[str]:
        """Collect unique loaded models across eligible devices."""
        models: set[str] = set()
        for d in devices:
            if d.model_loaded:
                models.add(d.model_loaded)
        return sorted(models)

    # ── Quantization-aware routing ───────────────────────────

    def suggest_quantization(self, device: MeshDeviceInfo) -> str:
        """Suggest quantization level based on device thermal state.

        Q4 = lower quality, less compute, less heat
        Q8 = higher quality, more compute, more heat
        """
        if device.cpu_temp_c > 70 or device.gpu_temp_c > 75:
            return "Q4_K_M"  # Reduce quality to reduce heat
        if device.battery_temp_c > 38:
            return "Q4_K_M"
        if device.ram_percent > 85:
            return "Q4_K_M"  # Also reduce if RAM pressure
        return "Q8_0"  # Full quality when thermal headroom exists
