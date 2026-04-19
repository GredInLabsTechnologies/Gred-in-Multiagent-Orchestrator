from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..config import OPS_DATA_DIR
from ..config import OPS_DATA_DIR
from ..ops_models import ToolEntry, McpServerConfig


class ToolRegistryService:
    """Allowlist registry for tools (fail-closed on unknown tools)."""

    # These paths are derived from OPS_DATA_DIR (server config) and a constant
    # filename — no user-controlled component. Sonar S2083/S6549 reports here
    # are false positives; kept safe via fixed string literals.
    REGISTRY_PATH: Path = OPS_DATA_DIR / "tool_registry.json"
    DISCOVERED_PATH: Path = OPS_DATA_DIR / "tool_registry_discovered.json"

    @classmethod
    def _load(cls) -> Dict[str, Dict]:
        if not cls.REGISTRY_PATH.exists():
            return {}
        try:
            raw = json.loads(cls.REGISTRY_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            return {}
        except Exception:
            return {}

    @classmethod
    def _save(cls, data: Dict[str, Dict]) -> None:
        cls.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def _load_discovered(cls) -> Dict[str, Dict]:
        if not cls.DISCOVERED_PATH.exists():
            return {}
        try:
            raw = json.loads(cls.DISCOVERED_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            return {}
        except Exception:
            return {}

    @classmethod
    def _save_discovered(cls, data: Dict[str, Dict]) -> None:
        cls.DISCOVERED_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.DISCOVERED_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def list_tools(cls) -> List[ToolEntry]:
        data = cls._load()
        discovered = cls._load_discovered()
        merged = {**discovered, **data}
        out: List[ToolEntry] = []
        for name, payload in merged.items():
            item = dict(payload)
            item.setdefault("name", name)
            out.append(ToolEntry.model_validate(item))
        out.sort(key=lambda t: t.name)
        return out

    @classmethod
    def get_tool(cls, name: str) -> Optional[ToolEntry]:
        data = cls._load()
        payload = data.get(name)
        if not payload:
            payload = cls._load_discovered().get(name)
        if not payload:
            return None
        item = dict(payload)
        item.setdefault("name", name)
        return ToolEntry.model_validate(item)

    @classmethod
    def report_tool(
        cls,
        *,
        name: str,
        description: str = "",
        risk: str = "read",
        inputs: Optional[Dict] = None,
        outputs: Optional[Dict] = None,
        estimated_cost: float = 0.0,
        requires_hitl: bool = True,
        metadata: Optional[Dict] = None,
    ) -> ToolEntry:
        """Record dynamically discovered tool metadata without auto-allowing it broadly.

        Discovered tools default to admin-only + requires_hitl to preserve fail-closed behavior.
        """
        discovered = cls._load_discovered()
        payload = dict(discovered.get(name) or {})
        payload.update(
            {
                "name": name,
                "description": description or payload.get("description", ""),
                "inputs": inputs or payload.get("inputs", {}),
                "outputs": outputs or payload.get("outputs", {}),
                "risk": risk if risk in {"read", "write", "destructive"} else payload.get("risk", "read"),
                "estimated_cost": float(estimated_cost or payload.get("estimated_cost", 0.0) or 0.0),
                "requires_hitl": bool(requires_hitl),
                "allowed_roles": payload.get("allowed_roles", ["admin"]),
                "metadata": payload.get("metadata", {}),
                "discovered": True,
            }
        )
        entry = ToolEntry.model_validate(payload)
        discovered[name] = entry.model_dump()
        discovered[name]["discovered"] = True
        cls._save_discovered(discovered)
        return entry

    @classmethod
    def upsert_tool(cls, entry: ToolEntry) -> ToolEntry:
        data = cls._load()
        data[entry.name] = entry.model_dump()
        cls._save(data)
        return entry

    @classmethod
    def delete_tool(cls, name: str) -> bool:
        data = cls._load()
        if name not in data:
            return False
        data.pop(name, None)
        cls._save(data)
        return True

    @classmethod
    def is_allowed(cls, name: str, *, role: Optional[str] = None) -> bool:
        tool = cls.get_tool(name)
        if not tool:
            return False
        # Fail-closed when caller role is unknown and tool is not generally operator-safe.
        if role is None and tool.allowed_roles and "operator" not in set(tool.allowed_roles):
            return False
        if role and tool.allowed_roles and role not in set(tool.allowed_roles):
            return False
        return True

    @classmethod
    async def sync_mcp_tools(cls, server_name: str, config: McpServerConfig) -> List[ToolEntry]:
        """Connect to MCP server, list tools, and register them as discovered."""
        if not config.enabled:
            return []

        from ..adapters.mcp_client import McpClient

        async with McpClient(server_name, config) as client:
            tools = await client.list_tools()
        
        registered = []
        for tool in tools:
            # Prefix tool name with server name to avoid collisions
            # E.g. "github_read_file" -> "github_read_file"? 
            # Or "github:read_file"?
            # Let's use underscore for now as it's safer for function calling conventions in some LLMs
            tool_name = tool.get("name")
            if not tool_name:
                continue
                
            full_name = f"{server_name}_{tool_name}"
            
            # Map MCP tool definition to ToolEntry
            # MCP inputs schema is JSON Schema.
            inputs = tool.get("inputSchema") or {}
            description = tool.get("description") or ""
            
            entry = cls.report_tool(
                name=full_name,
                description=description,
                inputs=inputs,
                risk="read", # Default to read, admin can override
                requires_hitl=True, # Default to HITL for safety
            )
            # Update metadata ensuring we persist the link
            entry.metadata.update({
                "mcp_server": server_name,
                "mcp_tool": tool_name
            })
            cls.upsert_tool(entry) # Persist metadata updates
            
            registered.append(entry)
            
        return registered
