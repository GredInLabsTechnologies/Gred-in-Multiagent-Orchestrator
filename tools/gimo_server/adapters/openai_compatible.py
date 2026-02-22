from __future__ import annotations

import asyncio
import logging
import json
import time
from typing import Any, Dict, List, Optional
import httpx

from .base import (
    AgentAdapter, 
    AgentResult, 
    AgentSession, 
    AgentStatus, 
    ProposedAction
)
from ..services.tool_registry_service import ToolRegistryService

logger = logging.getLogger("orchestrator.adapters.openai_compatible")

class OpenAICompatibleSession(AgentSession):
    """Session for an OpenAI-compatible agent."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: str = "You are a helpful AI assistant.",
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.task = task
        self.status = AgentStatus.RUNNING
        self.created_at = time.perf_counter()
        
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task}\nContext: {json.dumps(context or {})}"}
        ]
        
        self._proposals: List[ProposedAction] = []
        self._proposal_index: Dict[str, ProposedAction] = {}
        self._decision_log: Dict[str, str] = {}
        self._metrics: Dict[str, Any] = {"tokens_used": 0, "cost_usd": 0.0}
        
        self._background_task = asyncio.create_task(self._process_turn())

    async def _process_turn(self):
        """Executes a turn: sends messages to LLM, parses response."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model_name,
                        "messages": self.messages,
                        "temperature": 0.0,
                        "stream": False, 
                        # Tool definitions would go here for real function calling
                        # For MVP we might parse text or assume JSON mode if the model supports it.
                        # Phi-3.5 and Qwen support tools usually.
                        # For robustness, let's prompt for JSON tool calls if not using native tools.
                    },
                    timeout=300.0
                )
                response.raise_for_status()
                data = response.json()
                
                choice = data["choices"][0]
                message = choice["message"]
                self.messages.append(message)
                
                # Check for tool calls (native)
                tool_calls = message.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        action = ProposedAction(
                            id=tc["id"],
                            tool=tc["function"]["name"],
                            params=json.loads(tc["function"]["arguments"]),
                            description="LLM Tool Call"
                        )
                        self._register_proposal(action)
                    self.status = AgentStatus.PAUSED
                else:
                    # No tool calls, we consider it done for this turn
                    # Or we could check if it's a final answer?
                    # For MVP, if no tools, it's COMPLETED unless we explicitly loop.
                    self.status = AgentStatus.COMPLETED

                usage = data.get("usage", {})
                self._metrics["tokens_used"] += usage.get("total_tokens", 0)

        except Exception as e:
            logger.error(f"OpenAI-compatible LLM error: {e}")
            self.status = AgentStatus.FAILED
            self._metrics["error"] = str(e)

    def _register_proposal(self, action: ProposedAction):
        self._proposal_index[action.id] = action
        self._proposals.append(action)

    async def get_status(self) -> AgentStatus:
        return self.status

    async def capture_proposals(self) -> List[ProposedAction]:
        return list(self._proposals)

    async def allow(self, action_id: str) -> None:
        if action_id not in self._proposal_index:
            raise ValueError(f"Unknown proposal id: {action_id}")
        
        action = self._proposal_index[action_id]
        self._decision_log[action_id] = "allowed"
        
        # Execute tool (Mock execution for now, or via ToolRegistry)
        # In a real implementation we'd call ToolRegistryService.execute(action.tool, action.params)
        # using execute logic. 
        # For this MVP, let's assume valid tools are executed.
        
        try:
            # We need to execute the tool here!
            # Since adapter base doesn't have execute method, we'll mock or shell out.
            # Ideally we import ToolRegistryService and use it.
            
            # Simple mock execution for common tools
            output = f"Tool {action.tool} executed successfully."
            
            # Append result message
            self.messages.append({
                "role": "tool",
                "tool_call_id": action.id,
                "content": output
            })
            
            # Continue conversation
            self.status = AgentStatus.RUNNING
            self._proposals = [] # Clear handled proposals? Or keep history?
            # Usually we clear active proposals list for next turn.
            self._proposals = [p for p in self._proposals if p.id != action_id]
            
            self._background_task = asyncio.create_task(self._process_turn())
            
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            # Send error back to LLM
            self.messages.append({
                "role": "tool", 
                "tool_call_id": action.id,
                "content": f"Error: {str(e)}"
            })
            self._background_task = asyncio.create_task(self._process_turn())

    async def deny(self, action_id: str, reason: Optional[str] = None) -> None:
        if action_id not in self._proposal_index:
            raise ValueError(f"Unknown proposal id: {action_id}")
            
        self._decision_log[action_id] = f"denied:{reason}"
        
        self.messages.append({
            "role": "tool",
            "tool_call_id": action_id,
            "content": f"User denied this action. Reason: {reason or 'No reason provided'}"
        })
        
        self._proposals = [p for p in self._proposals if p.id != action_id]
        self.status = AgentStatus.RUNNING
        self._background_task = asyncio.create_task(self._process_turn())

    async def get_result(self) -> AgentResult:
        if self._background_task:
            await self._background_task
            
        last_msg = self.messages[-1]
        output = last_msg.get("content") if last_msg["role"] == "assistant" else None
        
        return AgentResult(
            status=self.status,
            output=output,
            metrics=self._metrics,
            error=self._metrics.get("error")
        )

    async def kill(self) -> None:
        if self._background_task:
            self._background_task.cancel()
        self.status = AgentStatus.KILLED


class OpenAICompatibleAdapter(AgentAdapter):
    """Adapter for LLMs via OpenAI-compatible API.

    Compatible with any provider exposing an OpenAI-like /v1/chat/completions endpoint:
    - Ollama (default: http://localhost:11434/v1)
    - LM Studio (default: http://localhost:1234/v1)
    - vLLM
    - DeepSeek

    Attributes:
        base_url (str): The API base URL.
        model_name (str): The model identifier to request.
        system_prompt (str): Default system prompt.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model_name: str = "local-model",
        system_prompt: str = "You are a helpful AI assistant."
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.system_prompt = system_prompt

    async def spawn(
        self, 
        task: str, 
        context: Optional[Dict[str, Any]] = None, 
        policy: Optional[Dict[str, Any]] = None
    ) -> AgentSession:
        logger.info(f"Spawning OpenAI-compatible LLM Session: {self.model_name}")
        return OpenAICompatibleSession(
            base_url=self.base_url,
            model_name=self.model_name,
            task=task,
            context=context,
            system_prompt=self.system_prompt
        )
