from __future__ import annotations

import logging
import os
import fnmatch
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, List
from ...services.file_service import FileService
from ..moods import get_mood_profile, MoodProfile  # P2: Import mood engine

logger = logging.getLogger(__name__)

class ToolExecutionResult(Dict[str, Any]):
    def __init__(self, status: str, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__({"status": status, "message": message, "data": data or {}})

class ToolExecutor:
    """
    Handles execution of artifact tools with safety checks.

    P2: Enhanced with mood-based tool constraints (whitelist/blacklist/requires_confirmation).
    """
    def __init__(
        self,
        workspace_root: str,
        policy: Optional[Dict[str, Any]] = None,
        token: str = "SYSTEM",
        mood: str = "neutral",
    ):
        self.workspace_root = workspace_root
        self.policy = policy or {}
        self.token = token
        self.mood = mood
        self._mood_profile: Optional[MoodProfile] = None

        # Load mood profile if valid
        try:
            self._mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning(f"Invalid mood '{mood}', using neutral")
            self._mood_profile = get_mood_profile("neutral")

    def _is_tool_allowed(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """Check if a tool is allowed by the current mood profile.

        Returns: (is_allowed, reason_if_denied)
        """
        if not self._mood_profile:
            return True, None

        # Check blacklist first
        if tool_name in self._mood_profile.tool_blacklist:
            return False, f"Tool '{tool_name}' is blacklisted in {self.mood} mood"

        # Check whitelist (empty whitelist = all allowed)
        if self._mood_profile.tool_whitelist:
            if tool_name not in self._mood_profile.tool_whitelist:
                allowed_tools = ", ".join(sorted(self._mood_profile.tool_whitelist))
                return False, f"Tool '{tool_name}' not in {self.mood} mood whitelist. Allowed: {allowed_tools}"

        return True, None

    def _requires_confirmation(self, tool_name: str) -> bool:
        """Check if a tool requires user confirmation before execution."""
        if not self._mood_profile:
            return False
        return tool_name in self._mood_profile.requires_confirmation

    def _is_path_allowed(self, full_path: str) -> bool:
        allowed_paths = []
        if hasattr(self.policy, "allowed_paths"):
            allowed_paths = list(getattr(self.policy, "allowed_paths") or [])
        elif isinstance(self.policy, dict):
            allowed_paths = list(self.policy.get("allowed_paths") or [])
        if not allowed_paths or "*" in allowed_paths:
            return True

        normalized = full_path.replace("\\", "/")
        rel_normalized = normalized
        try:
            rel_normalized = os.path.relpath(full_path, self.workspace_root).replace("\\", "/")
        except Exception:
            rel_normalized = normalized
        for allowed in allowed_paths:
            allowed_norm = str(allowed).replace("\\", "/")
            if (
                normalized == allowed_norm
                or normalized.startswith(f"{allowed_norm}/")
                or rel_normalized == allowed_norm
                or rel_normalized.startswith(f"{allowed_norm}/")
                or fnmatch.fnmatch(normalized, allowed_norm)
                or fnmatch.fnmatch(rel_normalized, allowed_norm)
            ):
                return True
        return False


    async def execute_tool_call(self, name: str, arguments: Dict[str, Any]) -> ToolExecutionResult:
        """Routes a tool call to the appropriate internal handler.

        P2: Validates mood-based tool constraints before execution.
        """
        # P2: Validate tool is allowed by mood
        is_allowed, deny_reason = self._is_tool_allowed(name)
        if not is_allowed:
            return ToolExecutionResult("error", deny_reason or f"Tool '{name}' not allowed")

        # P2: Check if tool requires user confirmation
        if self._requires_confirmation(name):
            # Return special status to trigger ask_user flow
            return ToolExecutionResult("requires_confirmation", f"Tool '{name}' requires user approval in {self.mood} mood", {
                "tool_name": name,
                "arguments": arguments,
                "mood": self.mood,
            })

        handler = getattr(self, f"handle_{name}", None)
        if not handler:
            return ToolExecutionResult("error", f"Unknown tool: {name}")

        try:
            return await handler(arguments)
        except Exception as e:
            logger.exception(f"Error executing tool {name}")
            return ToolExecutionResult("error", f"Internal error in {name}: {str(e)}")

    async def handle_write_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        content = args.get("content", "")
        if not path:
            return ToolExecutionResult("error", "Missing 'path' argument")
            
        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")
        logger.info(f"Writing {len(content)} characters to {full_path}")
        FileService.write_file(Path(full_path), str(content), self.token)
        return ToolExecutionResult("success", f"File written: {path}", {"path": full_path, "size": len(content)})


    async def handle_patch_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        diff = args.get("diff")
        if not path or not diff:
            return ToolExecutionResult("error", "Missing 'path' or 'diff' argument")
        
        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")
        FileService.patch_file(Path(full_path), diff=str(diff), token=self.token)
        return ToolExecutionResult("success", f"File patched: {path}")

    async def handle_create_dir(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        if not path:
            return ToolExecutionResult("error", "Missing 'path' argument")
        
        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")
        FileService.create_dir(Path(full_path), self.token)
        return ToolExecutionResult("success", f"Directory created: {path}")


    def _to_abs_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.workspace_root, path))

    async def handle_read_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Read file contents with optional line range."""
        path = args.get("path")
        if not path:
            return ToolExecutionResult("error", "Missing 'path' argument")

        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")

        try:
            start_line = args.get("start_line", 1)
            end_line = args.get("end_line", 999999)

            content, content_hash = FileService.get_file_content(
                Path(full_path),
                start_line=start_line,
                end_line=end_line,
                token=self.token
            )

            return ToolExecutionResult(
                "success",
                f"Read {len(content)} characters from {path}",
                {"content": content, "hash": content_hash}
            )
        except Exception as e:
            logger.exception(f"Error reading file {path}")
            return ToolExecutionResult("error", f"Failed to read file: {str(e)}")

    async def handle_list_files(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """List files in directory with optional pattern and depth."""
        path = args.get("path", ".")
        max_depth = args.get("max_depth", 2)
        pattern = args.get("pattern")

        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")

        try:
            root = Path(full_path)
            if not root.exists():
                return ToolExecutionResult("error", f"Path does not exist: {path}")

            if not root.is_dir():
                return ToolExecutionResult("error", f"Path is not a directory: {path}")

            # Collect files respecting max_depth
            files: List[str] = []
            gitignore_patterns = self._load_gitignore(root)

            def should_ignore(rel_path: str) -> bool:
                # Skip hidden and common ignore patterns
                parts = Path(rel_path).parts
                if any(p.startswith('.') for p in parts):
                    return True
                if any(p in {'node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build'} for p in parts):
                    return True
                # Check gitignore patterns
                for ignore_pat in gitignore_patterns:
                    if fnmatch.fnmatch(rel_path, ignore_pat):
                        return True
                return False

            for item in root.rglob("*"):
                try:
                    rel_path = item.relative_to(root)
                    depth = len(rel_path.parts)

                    if depth > max_depth:
                        continue

                    rel_str = str(rel_path).replace("\\", "/")

                    if should_ignore(rel_str):
                        continue

                    if pattern and not fnmatch.fnmatch(item.name, pattern):
                        continue

                    if item.is_file():
                        files.append(rel_str)

                    if len(files) >= 100:  # Safety limit
                        break
                except Exception:
                    continue

            files.sort()
            return ToolExecutionResult(
                "success",
                f"Found {len(files)} files in {path}",
                {"files": files, "count": len(files)}
            )
        except Exception as e:
            logger.exception(f"Error listing files in {path}")
            return ToolExecutionResult("error", f"Failed to list files: {str(e)}")

    def _load_gitignore(self, root: Path) -> List[str]:
        """Load gitignore patterns from .gitignore file."""
        gitignore_file = root / ".gitignore"
        patterns = []
        if gitignore_file.exists():
            try:
                for line in gitignore_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line.rstrip("/"))
            except Exception:
                pass
        return patterns

    async def handle_search_text(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Search for text pattern in files using grep."""
        pattern = args.get("pattern")
        if not pattern:
            return ToolExecutionResult("error", "Missing 'pattern' argument")

        path = args.get("path", ".")
        glob_pattern = args.get("glob")
        max_results = args.get("max_results", 100)

        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")

        try:
            # Try to use ripgrep if available, fallback to grep
            cmd_parts = []

            # Check if rg is available
            try:
                subprocess.run(["rg", "--version"], capture_output=True, check=True)
                cmd_parts = ["rg", "--line-number", "--no-heading", "--color=never"]
                if glob_pattern:
                    cmd_parts.extend(["--glob", glob_pattern])
                cmd_parts.extend([pattern, full_path])
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback to grep
                cmd_parts = ["grep", "-rn", pattern, full_path]
                if glob_pattern:
                    cmd_parts.extend(["--include", glob_pattern])

            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=10
            )

            lines = result.stdout.splitlines()[:max_results]

            return ToolExecutionResult(
                "success",
                f"Found {len(lines)} matches for '{pattern}'",
                {"matches": lines, "count": len(lines)}
            )
        except subprocess.TimeoutExpired:
            return ToolExecutionResult("error", "Search timeout exceeded")
        except Exception as e:
            logger.exception(f"Error searching for pattern '{pattern}'")
            return ToolExecutionResult("error", f"Failed to search: {str(e)}")

    async def handle_search_replace(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Search and replace text in a file."""
        path = args.get("path")
        old_text = args.get("old_text")
        new_text = args.get("new_text")

        if not path or old_text is None or new_text is None:
            return ToolExecutionResult("error", "Missing required arguments: path, old_text, new_text")

        full_path = self._to_abs_path(path)
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")

        try:
            # Read current content
            content, _ = FileService.get_file_content(Path(full_path), token=self.token)

            # Check that old_text is unique
            count = content.count(old_text)
            if count == 0:
                return ToolExecutionResult("error", f"Text not found in file: {old_text[:50]}...")
            elif count > 1:
                return ToolExecutionResult("error", f"Text appears {count} times in file, must be unique")

            # Perform replacement
            new_content = content.replace(old_text, new_text)
            FileService.write_file(Path(full_path), new_content, self.token)

            return ToolExecutionResult(
                "success",
                f"Replaced text in {path}",
                {"old_length": len(old_text), "new_length": len(new_text)}
            )
        except Exception as e:
            logger.exception(f"Error in search_replace for {path}")
            return ToolExecutionResult("error", f"Failed to replace: {str(e)}")

    async def handle_shell_exec(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Execute a shell command with timeout."""
        command = args.get("command")
        if not command:
            return ToolExecutionResult("error", "Missing 'command' argument")

        timeout = args.get("timeout", 30)

        try:
            logger.warning(f"Executing shell command: {command}")

            # Run in workspace directory
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_root
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolExecutionResult("error", f"Command timeout after {timeout}s")

            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""

            return ToolExecutionResult(
                "success" if proc.returncode == 0 else "error",
                f"Command exited with code {proc.returncode}",
                {
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "returncode": proc.returncode
                }
            )
        except Exception as e:
            logger.exception(f"Error executing command: {command}")
            return ToolExecutionResult("error", f"Failed to execute: {str(e)}")

    # ── P2: Meta-Tools ────────────────────────────────────────────────────────

    async def handle_ask_user(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Pause the loop and ask the user a question.

        Returns a special status that signals the agentic loop to pause and wait for user input.
        """
        question = args.get("question")
        if not question:
            return ToolExecutionResult("error", "Missing 'question' argument")

        options = args.get("options", [])
        context = args.get("context", "")

        # Return special status to pause loop
        return ToolExecutionResult("user_question", question, {
            "question": question,
            "options": options,
            "context": context,
        })

    async def handle_propose_plan(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Propose an execution plan for user approval.

        Returns a special status that signals the agentic loop to pause and wait for plan approval.
        """
        title = args.get("title")
        objective = args.get("objective")
        tasks = args.get("tasks", [])

        if not title or not objective:
            return ToolExecutionResult("error", "Missing 'title' or 'objective'")

        if not tasks:
            return ToolExecutionResult("error", "Plan must include at least one task")

        # Validate tasks structure
        for idx, task in enumerate(tasks):
            if not isinstance(task, dict):
                return ToolExecutionResult("error", f"Task {idx} is not a valid object")
            if not task.get("id") or not task.get("title"):
                return ToolExecutionResult("error", f"Task {idx} missing 'id' or 'title'")
            if not task.get("agent_rationale"):
                return ToolExecutionResult("error", f"Task {task.get('id')} missing 'agent_rationale' (explain WHY you chose this mood)")

        # Return special status to pause loop for plan review
        return ToolExecutionResult("plan_proposed", f"Proposed plan: {title}", {
            "title": title,
            "objective": objective,
            "tasks": tasks,
        })

    async def handle_web_search(self, args: Dict[str, Any]) -> ToolExecutionResult:
        """Search the web for information.

        P2: Proxies to existing web search infrastructure if available, otherwise returns placeholder.
        """
        query = args.get("query")
        if not query:
            return ToolExecutionResult("error", "Missing 'query' argument")

        try:
            # Try to import and use existing web search service
            from ...services.web_search_service import WebSearchService

            results = await WebSearchService.search(query, max_results=5)
            if not results:
                return ToolExecutionResult("success", f"No results found for: {query}", {"results": []})

            # Format results
            formatted = "\n\n".join([
                f"[{i+1}] {r.get('title', 'Untitled')}\n{r.get('snippet', '')}\nURL: {r.get('url', '')}"
                for i, r in enumerate(results[:5])
            ])

            return ToolExecutionResult("success", f"Found {len(results)} results for: {query}", {
                "query": query,
                "results": results,
                "formatted": formatted,
            })
        except ImportError:
            # Fallback: return placeholder if web search not configured
            logger.warning("WebSearchService not available, returning placeholder")
            return ToolExecutionResult("success", f"[Web search placeholder] Query: {query}", {
                "query": query,
                "results": [],
                "note": "Web search not configured. Install a web search provider to enable this feature.",
            })
        except Exception as e:
            logger.exception(f"Error in web_search for query: {query}")
            return ToolExecutionResult("error", f"Web search failed: {str(e)}")
