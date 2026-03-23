"""SwarmMixin — Fase 6 de GraphEngine v2.

Handoff descentralizado entre agentes con:
- Loop de ejecución con active_agent en state
- Handoff tools generados dinámicamente por agente
- MoodContracts por agente (compatibilidad de moods)
- Execution proof por cada handoff
- Routing inteligente via CapabilityProfileService
- GICS: ops:handoff_stats:{agent_from}:{agent_to}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger("orchestrator.services.swarm")

# Matriz de compatibilidad de moods:
# Si el agente receptor tiene un mood más restrictivo, se registra advertencia.
_MOOD_COMPAT: Dict[str, set] = {
    "autonomous":    {"autonomous", "standard", "conservative"},
    "standard":      {"autonomous", "standard", "conservative"},
    "conservative":  {"autonomous", "standard", "conservative"},
    "critical":      set(),  # critical requiere siempre aprobación explícita
}


class SwarmMixin:
    """Swarm: handoff descentralizado entre agentes."""

    async def _run_swarm(self, node) -> Dict[str, Any]:
        """Loop de ejecución descentralizado.

        Recorre agentes por handoff hasta que ninguno pide continuar
        o se alcanza max_iterations.
        """
        agents_config: List[Dict[str, Any]] = node.config.get("agents", [])
        max_iters = int(node.config.get("max_iterations", 10) or 10)
        start_agent_id: Optional[str] = (
            node.config.get("start_agent")
            or (agents_config[0].get("id") if agents_config else None)
        )

        agents: Dict[str, Dict[str, Any]] = {a["id"]: a for a in agents_config if a.get("id")}

        active_agent_id: Optional[str] = start_agent_id
        handoff_chain: List[Dict[str, Any]] = []
        proofs: List[Dict[str, Any]] = []
        iteration = 0

        while active_agent_id and iteration < max_iters:
            iteration += 1
            agent = agents.get(active_agent_id)
            if not agent:
                logger.warning("Swarm: agente '%s' no encontrado en el registry", active_agent_id)
                break

            self.state.data["active_agent"] = active_agent_id

            # Routing inteligente — seleccionar mejor modelo para este agente
            selected_model = self._recommend_swarm_model(agent)

            # Context filtering: usar context_keys si el agente las define
            context_keys: List[str] = agent.get("context_keys") or []
            agent_context = (
                {k: self.state.data.get(k) for k in context_keys}
                if context_keys
                else dict(self.state.data)
            )

            payload = {
                "role": "swarm_agent",
                "agent_id": active_agent_id,
                "agent_name": agent.get("name", active_agent_id),
                "instructions": agent.get("instructions", ""),
                "tools": agent.get("tools", []),
                "handoff_targets": agent.get("handoff_targets", []),
                "mood": agent.get("mood"),
                "context": agent_context,
                "selected_model": selected_model,
            }

            output = await self._run_agent_child(
                node,
                child_suffix=f"swarm_{active_agent_id}_{iteration}",
                payload=payload,
            )

            proof = {
                "agent_id": active_agent_id,
                "iteration": iteration,
                "mood": agent.get("mood"),
                "model": selected_model,
                "output_keys": list(output.keys()) if isinstance(output, dict) else [],
            }
            proofs.append(proof)

            handoff_to: Optional[str] = output.get("handoff_to") if isinstance(output, dict) else None

            if not handoff_to:
                # Sin handoff — swarm completado
                active_agent_id = None
                break

            # Validar que el target está en handoff_targets
            allowed: List[str] = agent.get("handoff_targets") or []
            if allowed and handoff_to not in allowed:
                logger.warning(
                    "Swarm: agente '%s' intenta handoff a '%s' (no está en targets %s)",
                    active_agent_id, handoff_to, allowed,
                )
                self.state.data["swarm_handoff_blocked"] = {
                    "from": active_agent_id,
                    "to": handoff_to,
                    "reason": "target_not_allowed",
                }
                break

            # MoodContract check
            target_agent = agents.get(handoff_to) or {}
            if not self._check_mood_compat(agent, target_agent):
                self.state.data["swarm_mood_violation"] = {
                    "from": active_agent_id,
                    "to": handoff_to,
                    "from_mood": agent.get("mood"),
                    "to_mood": target_agent.get("mood"),
                }
                logger.warning(
                    "Swarm MoodContract violation: %s(%s) → %s(%s)",
                    active_agent_id, agent.get("mood"),
                    handoff_to, target_agent.get("mood"),
                )
                break

            # Handoff válido
            self._record_handoff_stat(active_agent_id, handoff_to)
            handoff_chain.append({
                "from": active_agent_id,
                "to": handoff_to,
                "iteration": iteration,
                "from_mood": agent.get("mood"),
                "to_mood": target_agent.get("mood"),
            })
            active_agent_id = handoff_to

        return {
            "pattern": "swarm",
            "active_agent": self.state.data.get("active_agent"),
            "handoff_chain": handoff_chain,
            "proofs": proofs,
            "iterations": iteration,
        }

    # ── Helpers ──────────────────────────────────────────────

    def _recommend_swarm_model(self, agent: Dict[str, Any]) -> Optional[str]:
        """Usa CapabilityProfileService para recomendar modelo por task_type."""
        task_type = agent.get("task_type") or agent.get("name") or "agent_task"
        try:
            from tools.gimo_server.services.capability_profile_service import CapabilityProfileService
            rec = CapabilityProfileService.recommend_model_for_task(task_type=task_type)
            if rec:
                return rec.get("model_id")
        except Exception as e:
            logger.debug("CapabilityProfileService unavailable: %s", e)
        return None

    def _check_mood_compat(self, from_agent: Dict[str, Any], to_agent: Dict[str, Any]) -> bool:
        """Verifica compatibilidad de moods entre agentes.

        Retorna False si el handoff viola un MoodContract.
        """
        from_mood: Optional[str] = from_agent.get("mood")
        to_mood: Optional[str] = to_agent.get("mood")

        if not from_mood or not to_mood:
            return True  # Sin mood definido → compatible

        allowed_targets = _MOOD_COMPAT.get(from_mood, set())
        if not allowed_targets:
            # mood "critical" u otro sin tabla → bloquear
            return False

        return to_mood in allowed_targets

    def _record_handoff_stat(self, agent_from: str, agent_to: str) -> None:
        gics = getattr(self, "_gics", None)
        if not gics:
            return
        key = f"ops:handoff_stats:{agent_from}:{agent_to}"
        try:
            gics.put(key, {"from": agent_from, "to": agent_to})
        except Exception as e:
            logger.debug("GICS handoff_stats record failed: %s", e)
