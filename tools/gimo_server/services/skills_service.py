from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from filelock import FileLock
from pydantic import BaseModel, Field, field_validator

from ..config import OPS_DATA_DIR
from ..engine.moods import MoodType, MOOD_PROMPTS  # P2: Import moods from central engine

logger = logging.getLogger("orchestrator.skills")

SKILLS_DIR = OPS_DATA_DIR / "skills"
SKILLS_LOCK = OPS_DATA_DIR / "skills.lock"
ANALYTICS_DIR = OPS_DATA_DIR / "skill_analytics"
MARKETPLACE_DIR = OPS_DATA_DIR / "skill_marketplace"
COMMAND_RE = re.compile(r"^/[a-z0-9_-]{2,32}$")
SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,80}$")

# ── Agent Moods (P2: Migrated to engine/moods.py) ─────────────────────────────
# MoodType and MOOD_PROMPTS now imported from central mood engine


class DuplicateCommandError(ValueError):
    """Raised when a skill command is already taken by another skill."""


class SkillDefinition(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    command: str
    replace_graph: bool = False
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # ── Innovation fields (backward-compatible defaults) ──
    version: int = 1
    mood: str = "neutral"  # forensic | executor | dialoger | creative | guardian | mentor
    tags: List[str] = Field(default_factory=list)
    author: str = ""
    published: bool = False

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: str) -> str:
        if not COMMAND_RE.fullmatch(value or ""):
            raise ValueError("command must match ^/[a-z0-9_-]{2,32}$")
        return value

    @field_validator("mood")
    @classmethod
    def _validate_mood(cls, value: str) -> str:
        if value not in MOOD_PROMPTS:
            raise ValueError(f"mood must be one of: {', '.join(MOOD_PROMPTS.keys())}")
        return value


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    command: str
    replace_graph: bool = False
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    mood: str = "neutral"
    tags: List[str] = Field(default_factory=list)
    author: str = ""

class SkillDescriptionRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    command: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class SkillExecuteRequest(BaseModel):
    replace_graph: bool = False
    context: Dict[str, Any] = Field(default_factory=dict)


class SkillExecuteResponse(BaseModel):
    skill_run_id: str
    skill_id: str
    replace_graph: bool
    status: str


class SkillAutoGenRequest(BaseModel):
    """Request to auto-generate a skill from natural language."""
    prompt: str = Field(min_length=5, max_length=4000)
    name_hint: str = Field(default="", max_length=120)
    replace_graph: bool = False
    mood: str = "neutral"


class SkillAnalytics(BaseModel):
    """Execution metrics for a skill."""
    skill_id: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    success_rate: float = 0.0
    avg_duration_seconds: float = 0.0
    total_tokens_used: int = 0
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None


class SkillUpdateRequest(BaseModel):
    """Request to update an existing skill (creates new version)."""
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    mood: Optional[str] = None
    replace_graph: Optional[bool] = None
    tags: Optional[List[str]] = None


@dataclass(frozen=True)
class _GraphEdge:
    source: str
    target: str


class SkillsService:
    """File-backed service for canonical visual Skills."""

    @classmethod
    def _lock_path(cls) -> Path:
        candidate = Path(SKILLS_LOCK)
        if candidate.parent == OPS_DATA_DIR:
            return SKILLS_DIR.parent / "skills.lock"
        return candidate

    @classmethod
    def _ensure_dir(cls) -> None:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _skill_path(cls, skill_id: str) -> Path:
        if not SAFE_ID_RE.fullmatch(skill_id):
            raise ValueError("Invalid skill_id")
        return SKILLS_DIR / f"{skill_id}.json"

    @classmethod
    def _atomic_write(cls, path: Path, payload: str) -> None:
        tmp = path.with_suffix(f".tmp.{os.urandom(4).hex()}")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def _extract_edge(cls, edge: Dict[str, Any]) -> _GraphEdge:
        source = edge.get("source") or edge.get("from") or edge.get("from_node")
        target = edge.get("target") or edge.get("to") or edge.get("to_node")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Each edge must include a non-empty source/from")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Each edge must include a non-empty target/to")
        return _GraphEdge(source=source, target=target)

    @classmethod
    def _validate_command(cls, command: str) -> None:
        if not COMMAND_RE.fullmatch(command or ""):
            raise ValueError("command must match ^/[a-z0-9_-]{2,32}$")

    @classmethod
    def _is_orchestrator_node(cls, node: Dict[str, Any]) -> bool:
        node_type = str(node.get("type") or node.get("node_type") or node.get("role") or "").lower()
        if node_type == "orchestrator":
            return True
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        data_type = str(data.get("type") or data.get("node_type") or data.get("role") or "").lower()
        return data_type == "orchestrator"

    @classmethod
    def _validate_graph(cls, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
        if not nodes:
            raise ValueError("nodes must contain exactly one orchestrator node")

        node_ids = []
        for node in nodes:
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError("Each node must include a non-empty id")
            node_ids.append(node_id)

        if len(set(node_ids)) != len(node_ids):
            raise ValueError("Duplicate node ids are not allowed")

        parsed_edges = [cls._extract_edge(e) for e in edges]
        known = set(node_ids)
        for edge in parsed_edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("Edge references unknown node id")

        cls._assert_single_orchestrator(nodes)
        cls._assert_no_cycles(node_ids, parsed_edges)

    @classmethod
    def _assert_single_orchestrator(cls, nodes: List[Dict[str, Any]]) -> None:
        orchestrator_count = sum(1 for n in nodes if cls._is_orchestrator_node(n))
        if orchestrator_count != 1:
            raise ValueError("Skill must have exactly one orchestrator node")

    @classmethod
    def _assert_no_cycles(cls, node_ids: List[str], parsed_edges: List[_GraphEdge]) -> None:
        graph: Dict[str, List[str]] = {nid: [] for nid in node_ids}
        for edge in parsed_edges:
            graph[edge.source].append(edge.target)

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for nxt in graph.get(node_id, []):
                if nxt not in visited:
                    if dfs(nxt):
                        return True
                elif nxt in in_stack:
                    return True
            in_stack.remove(node_id)
            return False

        for nid in graph:
            if nid not in visited and dfs(nid):
                raise ValueError("Skill graph must be a DAG")

    @classmethod
    def _slugify_id(cls, name: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower() or "skill"
        return f"{base}-{int(time.time() * 1000)}-{os.urandom(4).hex()}"

    @classmethod
    def list_skills(cls, use_lock: bool = True) -> List[SkillDefinition]:
        cls._ensure_dir()
        out: List[SkillDefinition] = []
        def _load() -> None:
            for f in SKILLS_DIR.glob("*.json"):
                try:
                    out.append(SkillDefinition.model_validate_json(f.read_text(encoding="utf-8")))
                except Exception as exc:
                    logger.warning("Failed to parse skill '%s': %s", f.name, exc)

        if use_lock:
            with FileLock(str(cls._lock_path())):
                _load()
        else:
            _load()
        return sorted(out, key=lambda s: s.updated_at, reverse=True)

    @classmethod
    def get_skill(cls, skill_id: str, use_lock: bool = True) -> Optional[SkillDefinition]:
        cls._ensure_dir()
        try:
            path = cls._skill_path(skill_id)
        except ValueError:
            return None
        if use_lock:
            lock = FileLock(str(cls._lock_path()))
        else:
            lock = None
        if lock is not None:
            lock.acquire()
        try:
            if not path.exists():
                return None
            return SkillDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        finally:
            if lock is not None:
                lock.release()

    @classmethod
    def _assert_command_unique(
        cls,
        command: str,
        exclude_id: Optional[str] = None,
        use_lock: bool = True,
    ) -> None:
        for skill in cls.list_skills(use_lock=use_lock):
            if skill.command == command and skill.id != exclude_id:
                raise DuplicateCommandError(f"command '{command}' already exists")

    @classmethod
    def create_skill(cls, req: SkillCreateRequest, use_lock: bool = True) -> SkillDefinition:
        cls._ensure_dir()
        cls._validate_command(req.command)
        cls._validate_graph(req.nodes, req.edges)

        def _do_create():
            cls._assert_command_unique(req.command, use_lock=False)
            skill = SkillDefinition(
                id=cls._slugify_id(req.name),
                name=req.name,
                description=req.description,
                command=req.command,
                replace_graph=req.replace_graph,
                nodes=req.nodes,
                edges=req.edges,
                mood=req.mood,
                tags=req.tags,
                author=req.author,
            )
            cls._atomic_write(cls._skill_path(skill.id), skill.model_dump_json(indent=2))
            return skill

        if use_lock:
            with FileLock(str(cls._lock_path())):
                skill = _do_create()
        else:
            skill = _do_create()

        logger.info("Skill created: %s (%s)", skill.name, skill.id)
        return skill

    @classmethod
    def delete_skill(cls, skill_id: str, use_lock: bool = True) -> bool:
        try:
            path = cls._skill_path(skill_id)
        except ValueError:
            return False

        def _do_delete():
            if not path.exists():
                return False
            path.unlink()
            return True

        if use_lock:
            with FileLock(str(cls._lock_path())):
                res = _do_delete()
        else:
            res = _do_delete()

        if res:
            logger.info("Skill deleted: %s", skill_id)
        return res

    @classmethod
    def generate_description(cls, req: SkillDescriptionRequest) -> str:
        node_count = len(req.nodes)
        edge_count = len(req.edges)
        command = req.command or "/skill"
        name = req.name.strip() if req.name else "Skill"
        if node_count == 0:
            return f"{name} ({command}) prepara un flujo visual reutilizable para ejecutar una automatización concreta."
        return (
            f"{name} ({command}) ejecuta un flujo visual con {node_count} nodos y {edge_count} "
            f"conexiones para completar una tarea de orquestación de forma repetible."
        )

    @classmethod
    async def execute_skill(cls, skill_id: str, req: SkillExecuteRequest) -> SkillExecuteResponse:
        from .custom_plan_service import CustomPlanService, CreatePlanRequest, PlanNode, PlanEdge, PlanNodePosition

        skill = cls.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill {skill_id} not found")

        skill_run_id = f"skill_run_{int(time.time())}_{os.urandom(2).hex()}"

        nodes = []
        mood_prefix = MOOD_PROMPTS.get(skill.mood, "")
        if mood_prefix:
            mood_prefix = mood_prefix + "\n\n"
        for n in skill.nodes:
            # map ui node format to CustomPlan node format
            node_type = str(n.get("type", "worker"))
            data = n.get("data", {})
            nodes.append(PlanNode(
                id=n.get("id", ""),
                label=data.get("label", n.get("id", "")),
                prompt=data.get("prompt", ""),
                model=data.get("model", "auto"),
                provider=data.get("provider", "auto"),
                role=data.get("role", node_type),
                node_type=node_type,
                role_definition=mood_prefix + data.get("system_prompt", ""),
                is_orchestrator=cls._is_orchestrator_node(n),
                position=PlanNodePosition(
                    x=n.get("position", {}).get("x", 0),
                    y=n.get("position", {}).get("y", 0),
                ),
                config=data,
            ))

        edges = []
        for e in skill.edges:
            parsed = cls._extract_edge(e)
            edges.append(PlanEdge(
                id=e.get("id", ""),
                source=parsed.source,
                target=parsed.target,
            ))

        plan_req = CreatePlanRequest(
            name=f"Run of {skill.name}",
            description=f"Automated execution for skill {skill.command}",
            nodes=nodes,
            edges=edges,
        )

        plan = CustomPlanService.create_plan(plan_req)

        # Trigger execution in background to not block
        import asyncio
        asyncio.create_task(
            cls._execute_plan_background(
                plan_id=plan.id,
                skill_id=skill.id,
                skill_run_id=skill_run_id,
                command=skill.command,
            )
        )

        return SkillExecuteResponse(
            skill_run_id=skill_run_id,
            skill_id=skill.id,
            replace_graph=req.replace_graph,
            status="queued"
        )
        
    @classmethod
    async def _execute_plan_background(
        cls,
        plan_id: str,
        skill_id: str,
        skill_run_id: str,
        command: str,
    ) -> None:
        from .custom_plan_service import CustomPlanService
        from .notification_service import NotificationService

        started_at = datetime.now(timezone.utc).isoformat()
        await NotificationService.publish("skill_execution_started", {
            "skill_run_id": skill_run_id,
            "skill_id": skill_id,
            "command": command,
            "status": "running",
            "progress": 0.0,
            "message": "Starting skill execution",
            "started_at": started_at,
            "finished_at": None,
        })
        
        try:
            plan = await CustomPlanService.execute_plan(
                plan_id,
                skill_id=skill_id,
                skill_run_id=skill_run_id,
                skill_command=command,
            )
            if not plan:
                raise ValueError(f"Plan {plan_id} not found or failed to execute")
                
            status = "completed" if plan.status == "done" else "error"
            await NotificationService.publish("skill_execution_finished", {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "command": command,
                "status": status,
                "progress": 1.0 if status == "completed" else 0.0,
                "message": f"Skill execution finished with status: {status}",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Error executing skill {skill_id} via plan {plan_id}: {e}")
            await NotificationService.publish("skill_execution_finished", {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "command": command,
                "status": "error",
                "progress": 0.0,
                "message": f"Skill execution failed: {str(e)}",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            cls.record_skill_run(skill_id, "error", 0.0, 0)

    # ── Versioning ────────────────────────────────────────────────────────────

    @classmethod
    def update_skill(cls, skill_id: str, req: SkillUpdateRequest) -> Optional[SkillDefinition]:
        """Update a skill, creating a new version and archiving the previous one."""
        cls._ensure_dir()
        with FileLock(str(cls._lock_path())):
            skill = cls.get_skill(skill_id, use_lock=False)
            if not skill:
                return None

            # Archive current version
            versions_dir = SKILLS_DIR / "versions" / skill_id
            versions_dir.mkdir(parents=True, exist_ok=True)
            archive_path = versions_dir / f"v{skill.version}.json"
            cls._atomic_write(archive_path, skill.model_dump_json(indent=2))

            # Apply updates
            data = skill.model_dump()
            for field, val in req.model_dump(exclude_none=True).items():
                data[field] = val
            data["version"] = skill.version + 1
            data["updated_at"] = datetime.now(timezone.utc)

            # Re-validate if graph changed
            if req.nodes is not None or req.edges is not None:
                cls._validate_graph(data["nodes"], data["edges"])
            if req.mood is not None and req.mood not in MOOD_PROMPTS:
                raise ValueError(f"Invalid mood: {req.mood}")

            updated = SkillDefinition.model_validate(data)
            cls._atomic_write(cls._skill_path(skill_id), updated.model_dump_json(indent=2))
            logger.info("Skill updated: %s (v%d -> v%d)", skill_id, skill.version, updated.version)
            return updated

    @classmethod
    def list_skill_versions(cls, skill_id: str) -> List[SkillDefinition]:
        """List all archived versions of a skill."""
        versions_dir = SKILLS_DIR / "versions" / skill_id
        if not versions_dir.exists():
            return []
        out: List[SkillDefinition] = []
        for f in sorted(versions_dir.glob("v*.json")):
            try:
                out.append(SkillDefinition.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse version %s: %s", f.name, exc)
        return out

    # ── Auto-Generation from Natural Language ─────────────────────────────────

    @classmethod
    async def generate_skill_from_prompt(cls, req: SkillAutoGenRequest) -> SkillDefinition:
        """Generate a complete skill (nodes, edges, config) from a natural language prompt."""
        from .provider_service import ProviderService

        mood_instruction = MOOD_PROMPTS.get(req.mood, "")
        mood_suffix = f"\nAgent mood for all workers: {req.mood}. {mood_instruction}" if mood_instruction else ""

        sys_prompt = (
            "You are an AI skill architect. Generate a skill definition as JSON.\n"
            "RULES:\n"
            "- Output ONLY valid JSON, no markdown, no explanations\n"
            "- Must have exactly one node with type 'orchestrator'\n"
            "- Worker nodes should have type 'worker', 'reviewer', or 'researcher'\n"
            "- Each node needs: id, type, data: {label, system_prompt, model: 'auto'}\n"
            "- Each node needs: position: {x, y} (layout left-to-right, 250px apart)\n"
            "- Edges connect source -> target (orchestrator delegates to workers)\n"
            "- Edge ids: 'e-{source}-{target}'\n"
            f"{mood_suffix}\n\n"
            f"Task description: {req.prompt}\n\n"
            'JSON schema:\n'
            '{"name": "...", "description": "...", "command": "/auto-...",'
            ' "nodes": [{"id": "orch", "type": "orchestrator", "data": {"label": "...", "system_prompt": "...", "model": "auto"}, "position": {"x": 0, "y": 0}},'
            ' {"id": "w1", "type": "worker", "data": {"label": "...", "system_prompt": "...", "model": "auto"}, "position": {"x": 250, "y": 0}}],'
            ' "edges": [{"id": "e-orch-w1", "source": "orch", "target": "w1"}]}'
        )

        resp = await ProviderService.static_generate(
            sys_prompt, context={"task_type": "skill_auto_generation", "model": "auto"}
        )
        raw = resp.get("content", "").strip()

        # Parse JSON from LLM response (strip markdown fences if present)
        raw = re.sub(r"```(?:json)?\s*\n?", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]

        skill_data = json.loads(raw)

        # Build create request from LLM output
        name = req.name_hint or skill_data.get("name", "Auto-generated Skill")
        command = skill_data.get("command", f"/auto-{int(time.time())}")
        if not COMMAND_RE.fullmatch(command):
            command = f"/auto-{int(time.time()) % 100000}"

        create_req = SkillCreateRequest(
            name=name,
            description=skill_data.get("description", f"Auto-generated skill: {req.prompt[:100]}"),
            command=command,
            replace_graph=req.replace_graph,
            nodes=skill_data.get("nodes", []),
            edges=skill_data.get("edges", []),
            mood=req.mood,
            tags=["auto-generated"],
        )
        return cls.create_skill(create_req)

    # ── Analytics ──────────────────────────────────────────────────────────────

    @classmethod
    def _analytics_path(cls, skill_id: str) -> Path:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        return ANALYTICS_DIR / f"{skill_id}.json"

    @classmethod
    def get_skill_analytics(cls, skill_id: str) -> SkillAnalytics:
        """Get execution analytics for a skill."""
        path = cls._analytics_path(skill_id)
        if path.exists():
            try:
                return SkillAnalytics.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return SkillAnalytics(skill_id=skill_id)

    @classmethod
    def record_skill_run(
        cls, skill_id: str, status: str, duration: float = 0.0, tokens: int = 0
    ) -> SkillAnalytics:
        """Record a completed skill run in analytics."""
        analytics = cls.get_skill_analytics(skill_id)
        analytics.total_runs += 1
        if status == "completed":
            analytics.successful_runs += 1
        else:
            analytics.failed_runs += 1
        analytics.success_rate = (
            analytics.successful_runs / max(analytics.total_runs, 1)
        )
        # Running average for duration
        if duration > 0:
            prev_total = analytics.avg_duration_seconds * max(analytics.total_runs - 1, 1)
            analytics.avg_duration_seconds = (prev_total + duration) / analytics.total_runs
        analytics.total_tokens_used += tokens
        analytics.last_run_at = datetime.now(timezone.utc).isoformat()
        analytics.last_status = status

        cls._atomic_write(cls._analytics_path(skill_id), analytics.model_dump_json(indent=2))
        return analytics

    # ── Marketplace ────────────────────────────────────────────────────────────

    @classmethod
    def publish_skill(cls, skill_id: str, author: str = "") -> SkillDefinition:
        """Publish a skill to the local marketplace."""
        skill = cls.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill {skill_id} not found")

        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        skill.published = True
        skill.author = author or skill.author
        # Save to marketplace
        mp_path = MARKETPLACE_DIR / f"{skill.id}.json"
        cls._atomic_write(mp_path, skill.model_dump_json(indent=2))
        # Update original
        with FileLock(str(cls._lock_path())):
            cls._atomic_write(cls._skill_path(skill_id), skill.model_dump_json(indent=2))
        logger.info("Skill published to marketplace: %s", skill.name)
        return skill

    @classmethod
    def list_published_skills(cls) -> List[SkillDefinition]:
        """List all skills available in the marketplace."""
        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        out: List[SkillDefinition] = []
        for f in MARKETPLACE_DIR.glob("*.json"):
            try:
                out.append(SkillDefinition.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse marketplace skill '%s': %s", f.name, exc)
        return sorted(out, key=lambda s: s.updated_at, reverse=True)

    @classmethod
    def install_from_marketplace(cls, marketplace_skill_id: str) -> SkillDefinition:
        """Install a skill from the marketplace into local skills."""
        mp_path = MARKETPLACE_DIR / f"{marketplace_skill_id}.json"
        if not mp_path.exists():
            raise ValueError(f"Marketplace skill {marketplace_skill_id} not found")

        mp_skill = SkillDefinition.model_validate_json(mp_path.read_text(encoding="utf-8"))
        req = SkillCreateRequest(
            name=mp_skill.name,
            description=mp_skill.description,
            command=mp_skill.command,
            replace_graph=mp_skill.replace_graph,
            nodes=mp_skill.nodes,
            edges=mp_skill.edges,
            mood=mp_skill.mood,
            tags=mp_skill.tags + ["installed-from-marketplace"],
            author=mp_skill.author,
        )
        return cls.create_skill(req)

    # ── Moods helper ──────────────────────────────────────────────────────────

    @classmethod
    def get_mood_prompt(cls, mood: str) -> str:
        """Get the system prompt prefix for a given mood."""
        return MOOD_PROMPTS.get(mood, "")

    @classmethod
    def list_available_moods(cls) -> Dict[str, str]:
        """List all available moods with their descriptions."""
        return dict(MOOD_PROMPTS)
