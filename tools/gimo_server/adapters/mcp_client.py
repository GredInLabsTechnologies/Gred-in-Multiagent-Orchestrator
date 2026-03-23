from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

from ..ops_models import McpServerConfig

logger = logging.getLogger("orchestrator.adapters.mcp_client")


MCP_PROTOCOL_VERSION = "2024-11-05"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0


class McpClient:
    def __init__(self, server_name: str, config: McpServerConfig):
        self.server_name = server_name
        self.config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id_counter: int = 0

    async def __aenter__(self) -> "McpClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self) -> None:
        if self._process:
            return

        command = self.config.command
        args = self.config.args
        env = os.environ.copy()
        env.update(self.config.env)

        logger.info(f"Starting MCP server [{self.server_name}]: {command} {args}")
        try:
            self._process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as e:
            logger.error(f"Failed to start MCP server [{self.server_name}]: {e}")
            raise

    async def stop(self) -> None:
        if self._process:
            if self._process.stdin:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            try:
                self._process.terminate()
                await self._process.wait()
            except Exception:
                pass
            self._process = None

    def _next_request_id(self) -> int:
        self._request_id_counter += 1
        return self._request_id_counter

    async def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError("MCP server is not running")

        request_id = self._next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        message = json.dumps(payload) + "\n"
        self._process.stdin.write(message.encode("utf-8"))
        await self._process.stdin.drain()

        while True:
            line_bytes = await self._process.stdout.readline()
            if not line_bytes:
                if self._process.stderr:
                    stderr = await self._process.stderr.read()
                    logger.error(f"MCP Server [{self.server_name}] stderr: {stderr.decode('utf-8', errors='replace')}")
                raise RuntimeError(f"MCP server [{self.server_name}] exited unexpectedly")

            line = line_bytes.decode("utf-8").strip()
            if not line:
                continue

            result = self._parse_response(line, request_id)
            if result is not None:
                return result

    def _parse_response(self, line: str, request_id: int) -> Optional[Any]:
        try:
            data = json.loads(line)
            if data.get("jsonrpc") != "2.0":
                return None
            
            if "error" in data:
                if data.get("id") == request_id:
                     raise RuntimeError(f"MCP Error: {data['error']}")
                logger.warning(f"MCP Server [{self.server_name}] reported error for unknown ID: {data}")

            if data.get("id") == request_id:
                return data.get("result")
        except json.JSONDecodeError:
            logger.warning(f"MCP Server [{self.server_name}] produced non-JSON stdout: {line}")
        return None

    async def initialize(self) -> None:
        await self._send_request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "gimo-orchestrator", "version": "1.0.0"}
            }
        )
        if not self._process or not self._process.stdin:
             raise RuntimeError("MCP server not running")
             
        notify = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        self._process.stdin.write((json.dumps(notify) + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def connect(self) -> None:
        await self.start()
        await self.initialize()

    async def list_tools(self) -> List[Dict[str, Any]]:
        # Initial implementation fetches first page of tools
        # Pagination to be added if needed, but for now we trust `nextCursor` logic if we implement loop
        
        tools: List[Dict[str, Any]] = []
        cursor = None
        
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
                
            response = await self._send_request("tools/list", params)
            if not response:
                break
                
            page_tools = response.get("tools", [])
            tools.extend(page_tools)
            
            cursor = response.get("nextCursor")
            if not cursor:
                break
                
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                return await self._send_request("tools/call", {"name": name, "arguments": arguments})
            except RuntimeError as e:
                last_error = e
                if "exited unexpectedly" in str(e) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "MCP tool call '%s' failed (attempt %d/%d), retrying in %.1fs: %s",
                        name, attempt + 1, MAX_RETRIES, wait, e,
                    )
                    await asyncio.sleep(wait)
                    # Try to reconnect
                    try:
                        await self.stop()
                        await self.connect()
                    except Exception as reconnect_err:
                        logger.error("Reconnect failed: %s", reconnect_err)
                else:
                    raise
        raise last_error  # type: ignore[misc]
