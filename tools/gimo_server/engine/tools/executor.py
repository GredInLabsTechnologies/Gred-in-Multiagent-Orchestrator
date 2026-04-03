from __future__ import annotations

import asyncio
import fnmatch
import importlib.util
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ...services.file_service import FileService
from ...services.execution_policy_service import ExecutionPolicyProfile, ExecutionPolicyService
from ...services.task_descriptor_service import TaskDescriptorService
from ...services.workspace.workspace_contract import WorkspaceContract
from ..moods import get_mood_profile

logger = logging.getLogger(__name__)

_MUTATING_TOOLS = {"write_file", "patch_file", "search_replace", "create_dir"}
_NETWORK_TOOLS = {"web_search"}


class ToolExecutionResult(Dict[str, Any]):
    def __init__(self, status: str, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__({"status": status, "message": message, "data": data or {}})


class ToolExecutor:
    """Handles execution of artifact tools with execution-policy enforcement."""

    def __init__(
        self,
        workspace_root: str,
        policy: Optional[Dict[str, Any]] = None,
        token: str = "SYSTEM",
        mood: str = "neutral",
        execution_policy: Optional[str] = None,
        session_id: Optional[str] = None,
        workspace_contract: Optional[WorkspaceContract] = None,
    ):
        self.workspace_root = os.path.abspath(workspace_root)
        self._workspace_contract = workspace_contract
        self.policy = policy or {}
        self.token = token
        self.mood = mood
        if execution_policy:
            self.execution_policy = ExecutionPolicyService.canonical_policy_name(execution_policy)
        else:
            self.execution_policy = ExecutionPolicyService.policy_name_from_legacy_mood(mood)
        self.session_id = session_id
        try:
            self._policy_profile = ExecutionPolicyService.get_policy(self.execution_policy)
        except KeyError:
            logger.warning("Invalid execution policy '%s' for mood '%s', using workspace_safe", execution_policy, mood)
            self.execution_policy = "workspace_safe"
            self._policy_profile = ExecutionPolicyService.get_policy("workspace_safe")
        try:
            self._mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning("Invalid mood '%s', using neutral", mood)
            self.mood = "neutral"
            self._mood_profile = get_mood_profile("neutral")

    @property
    def _contract(self) -> ExecutionPolicyProfile:
        return self._policy_profile

    def _is_tool_allowed(self, tool_name: str) -> tuple[bool, Optional[str]]:
        if self._contract.allowed_tools and tool_name not in self._contract.allowed_tools:
            allowed_tools = ", ".join(sorted(self._contract.allowed_tools))
            return False, f"Tool '{tool_name}' not allowed by execution policy '{self.execution_policy}'. Allowed: {allowed_tools}"
        return True, None

    def _requires_confirmation(self, tool_name: str) -> bool:
        return tool_name in self._contract.requires_confirmation

    def _is_path_allowed(self, full_path: str) -> bool:
        allowed_paths: list[str] = []
        if isinstance(self.policy, dict):
            allowed_paths = list(self.policy.get("allowed_paths") or [])
        elif hasattr(self.policy, "allowed_paths"):
            allowed_paths = list(getattr(self.policy, "allowed_paths") or [])
            
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

    def _to_abs_path(self, path: str) -> str:
        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self.workspace_root, path))

    def _is_within_workspace(self, full_path: str) -> bool:
        try:
            common = os.path.commonpath([self.workspace_root, os.path.abspath(full_path)])
        except ValueError:
            return False
        return common == self.workspace_root

    def _validate_mutation_path(self, path: str) -> Optional[ToolExecutionResult]:
        full_path = self._to_abs_path(path)
        if self._contract.fs_mode == "read_only":
            return ToolExecutionResult("error", f"Execution policy '{self.execution_policy}' is read-only and cannot modify files")
        if self._contract.fs_mode == "workspace_only" and not self._is_within_workspace(full_path):
            return ToolExecutionResult("error", f"Path must stay inside workspace for execution policy '{self.execution_policy}': {path}")
        if not self._is_path_allowed(full_path):
            return ToolExecutionResult("error", f"Path not allowed by runtime policy: {path}")
        return None

    def _filter_web_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._contract.network_mode != "allowlist" or not self._contract.allowed_domains:
            return results
        filtered: list[dict[str, Any]] = []
        for result in results:
            url = str(result.get("url") or "")
            host = urlparse(url).netloc.lower().split(":")[0]
            if any(host == domain or host.endswith(f".{domain}") for domain in self._contract.allowed_domains):
                filtered.append(result)
        return filtered

    def _build_check_result(self, *, kind: str, command: list[str], cwd: str) -> dict[str, Any]:
        cmd_text = " ".join(command)
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part).strip()
            return {
                "kind": kind,
                "status": "success" if proc.returncode == 0 else "error",
                "command": cmd_text,
                "output": output,
                "returncode": proc.returncode,
            }
        except Exception as exc:
            return {
                "kind": kind,
                "status": "error",
                "command": cmd_text,
                "output": str(exc),
                "returncode": -1,
            }

    def _find_related_test(self, full_path: str) -> Optional[Path]:
        path = Path(full_path)
        if path.name.startswith("test_") and path.suffix == ".py":
            return path
        test_path = Path(self.workspace_root) / "tests" / f"test_{path.stem}.py"
        if test_path.exists():
            return test_path
        return None

    def _post_write_checks(self, full_path: str) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        if self._contract.auto_lint_on_write:
            if importlib.util.find_spec("ruff") is None:
                checks.append({
                    "kind": "lint",
                    "status": "skipped",
                    "command": "python -m ruff check <path>",
                    "output": "ruff not installed",
                })
            else:
                checks.append(
                    self._build_check_result(
                        kind="lint",
                        command=["python", "-m", "ruff", "check", full_path],
                        cwd=self.workspace_root,
                    )
                )
        if self._contract.auto_test_on_write:
            test_file = self._find_related_test(full_path)
            if not test_file:
                checks.append({
                    "kind": "test",
                    "status": "skipped",
                    "command": "python -m pytest -q <path>",
                    "output": "no related test file found",
                })
            else:
                checks.append(
                    self._build_check_result(
                        kind="test",
                        command=["python", "-m", "pytest", "-q", str(test_file)],
                        cwd=self.workspace_root,
                    )
                )
        return checks

    def _validate_shell_command(self, command: str) -> Optional[ToolExecutionResult]:
        for pattern in self._contract.shell_command_patterns:
            if re.match(pattern, command):
                return None
        return ToolExecutionResult(
            "error",
            f"Command '{command}' is not allowed by execution policy '{self.execution_policy}'",
        )

    async def execute_tool_call(self, name: str, arguments: Dict[str, Any]) -> ToolExecutionResult:
        # Gate: mutating tools require initialized workspace — auto-bootstrap
        if name in _MUTATING_TOOLS and not self._workspace_contract:
            try:
                self._workspace_contract = WorkspaceContract.ensure(self.workspace_root)
            except Exception as exc:
                logger.warning("Workspace bootstrap failed: %s", exc)
                return ToolExecutionResult(
                    "error",
                    f"Workspace not initialized and auto-bootstrap failed: {exc}. "
                    f"Run 'gimo init' or check workspace permissions.",
                )

        # Gate: protected paths
        if name in _MUTATING_TOOLS and self._workspace_contract:
            target_path = arguments.get("path", "")
            if target_path:
                try:
                    rel = os.path.relpath(
                        self._to_abs_path(target_path), self.workspace_root
                    ).replace("\\", "/")
                except ValueError:
                    rel = target_path
                if self._workspace_contract.is_path_protected(rel):
                    return ToolExecutionResult(
                        "error",
                        f"Path '{target_path}' is protected by workspace governance rules.",
                    )

        if name in _MUTATING_TOOLS and self._contract.fs_mode == "read_only":
            return ToolExecutionResult("error", f"Execution policy '{self.execution_policy}' is read-only and cannot execute '{name}'")
        if name in _NETWORK_TOOLS and self._contract.network_mode == "blocked":
            return ToolExecutionResult("error", f"Execution policy '{self.execution_policy}' blocks network tool '{name}'")

        is_allowed, deny_reason = self._is_tool_allowed(name)
        if not is_allowed:
            return ToolExecutionResult("error", deny_reason or f"Tool '{name}' not allowed")

        if self._requires_confirmation(name):
            return ToolExecutionResult(
                "requires_confirmation",
                f"Tool '{name}' requires user approval in execution policy '{self.execution_policy}'",
                {"tool_name": name, "arguments": arguments, "execution_policy": self.execution_policy},
            )

        handler = getattr(self, f"handle_{name}", None)
        if not handler:
            return ToolExecutionResult("error", f"Unknown tool: {name}")

        start_time = __import__("time").monotonic()
        try:
            result = await handler(arguments)
        except Exception as exc:
            logger.exception("Error executing tool %s", name)
            result = ToolExecutionResult("error", f"Internal error in {name}: {exc}")

        # Audit trail for mutating tools
        if name in _MUTATING_TOOLS and self._workspace_contract:
            elapsed = __import__("time").monotonic() - start_time
            self._workspace_contract.append_audit({
                "session_id": self.session_id or "",
                "tool": name,
                "path": arguments.get("path", ""),
                "result": result.get("status", "unknown"),
                "duration_s": round(elapsed, 3),
            })

        return result

    async def handle_write_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        content = args.get("content", "")
        if not path:
            return ToolExecutionResult("error", "Missing 'path' argument")
        error = self._validate_mutation_path(path)
        if error:
            return error

        full_path = self._to_abs_path(path)
        logger.info("Writing %d characters to %s", len(content), full_path)
        FileService.write_file(Path(full_path), str(content), self.token)
        return ToolExecutionResult(
            "success",
            f"File written: {path}",
            {
                "path": full_path,
                "size": len(content),
                "checks": self._post_write_checks(full_path),
            },
        )

    async def handle_patch_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        diff = args.get("diff")
        if not path or not diff:
            return ToolExecutionResult("error", "Missing 'path' or 'diff' argument")
        error = self._validate_mutation_path(path)
        if error:
            return error

        full_path = self._to_abs_path(path)
        FileService.patch_file(Path(full_path), diff=str(diff), token=self.token)
        return ToolExecutionResult(
            "success",
            f"File patched: {path}",
            {"path": full_path, "checks": self._post_write_checks(full_path)},
        )

    async def handle_create_dir(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        if not path:
            return ToolExecutionResult("error", "Missing 'path' argument")
        error = self._validate_mutation_path(path)
        if error:
            return error

        full_path = self._to_abs_path(path)
        FileService.create_dir(Path(full_path), self.token)
        return ToolExecutionResult("success", f"Directory created: {path}", {"path": full_path})

    async def handle_read_file(self, args: Dict[str, Any]) -> ToolExecutionResult:
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
                token=self.token,
            )
            return ToolExecutionResult(
                "success",
                f"Read {len(content)} characters from {path}",
                {"content": content, "hash": content_hash},
            )
        except Exception as exc:
            logger.exception("Error reading file %s", path)
            return ToolExecutionResult("error", f"Failed to read file: {exc}")

    async def handle_list_files(self, args: Dict[str, Any]) -> ToolExecutionResult:
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

            files: List[str] = []
            gitignore_patterns = self._load_gitignore(root)

            def should_ignore(rel_path: str) -> bool:
                parts = Path(rel_path).parts
                if any(part.startswith(".") for part in parts):
                    return True
                if any(part in {"node_modules", "__pycache__", "venv", ".venv", "dist", "build"} for part in parts):
                    return True
                return any(fnmatch.fnmatch(rel_path, ignore_pat) for ignore_pat in gitignore_patterns)

            for item in root.rglob("*"):
                try:
                    rel_path = item.relative_to(root)
                    if len(rel_path.parts) > max_depth:
                        continue
                    rel_str = str(rel_path).replace("\\", "/")
                    if should_ignore(rel_str):
                        continue
                    if pattern and not fnmatch.fnmatch(item.name, pattern):
                        continue
                    if item.is_file():
                        files.append(rel_str)
                    if len(files) >= 100:
                        break
                except Exception:
                    continue

            files.sort()
            return ToolExecutionResult("success", f"Found {len(files)} files in {path}", {"files": files, "count": len(files)})
        except Exception as exc:
            logger.exception("Error listing files in %s", path)
            return ToolExecutionResult("error", f"Failed to list files: {exc}")

    def _load_gitignore(self, root: Path) -> List[str]:
        gitignore_file = root / ".gitignore"
        patterns: list[str] = []
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
            try:
                subprocess.run(["rg", "--version"], capture_output=True, check=True)
                cmd_parts = ["rg", "--line-number", "--no-heading", "--color=never"]
                if glob_pattern:
                    cmd_parts.extend(["--glob", glob_pattern])
                cmd_parts.extend([pattern, full_path])
            except (subprocess.CalledProcessError, FileNotFoundError):
                cmd_parts = ["grep", "-rn", pattern, full_path]
                if glob_pattern:
                    cmd_parts.extend(["--include", glob_pattern])
            result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()[:max_results]
            return ToolExecutionResult("success", f"Found {len(lines)} matches for '{pattern}'", {"matches": lines, "count": len(lines)})
        except subprocess.TimeoutExpired:
            return ToolExecutionResult("error", "Search timeout exceeded")
        except Exception as exc:
            logger.exception("Error searching for pattern '%s'", pattern)
            return ToolExecutionResult("error", f"Failed to search: {exc}")

    async def handle_search_replace(self, args: Dict[str, Any]) -> ToolExecutionResult:
        path = args.get("path")
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        if not path or old_text is None or new_text is None:
            return ToolExecutionResult("error", "Missing required arguments: path, old_text, new_text")
        error = self._validate_mutation_path(path)
        if error:
            return error

        full_path = self._to_abs_path(path)
        try:
            content, _ = FileService.get_file_content(Path(full_path), token=self.token)
            count = content.count(old_text)
            if count == 0:
                return ToolExecutionResult("error", f"Text not found in file: {old_text[:50]}...")
            if count > 1:
                return ToolExecutionResult("error", f"Text appears {count} times in file, must be unique")
            new_content = content.replace(old_text, new_text)
            FileService.write_file(Path(full_path), new_content, self.token)
            return ToolExecutionResult(
                "success",
                f"Replaced text in {path}",
                {
                    "old_length": len(old_text),
                    "new_length": len(new_text),
                    "checks": self._post_write_checks(full_path),
                },
            )
        except Exception as exc:
            logger.exception("Error in search_replace for %s", path)
            return ToolExecutionResult("error", f"Failed to replace: {exc}")

    async def handle_shell_exec(self, args: Dict[str, Any]) -> ToolExecutionResult:
        command = args.get("command")
        if not command:
            return ToolExecutionResult("error", "Missing 'command' argument")
        timeout = args.get("timeout", 30)
        validation_error = self._validate_shell_command(str(command))
        if validation_error:
            return validation_error

        try:
            logger.warning("Executing shell command: %s", command)
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_root,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolExecutionResult("error", f"Command timeout after {timeout}s")

            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            return ToolExecutionResult(
                "success" if proc.returncode == 0 else "error",
                f"Command exited with code {proc.returncode}",
                {"stdout": stdout_text, "stderr": stderr_text, "returncode": proc.returncode},
            )
        except Exception as exc:
            logger.exception("Error executing command: %s", command)
            return ToolExecutionResult("error", f"Failed to execute: {exc}")

    async def handle_ask_user(self, args: Dict[str, Any]) -> ToolExecutionResult:
        question = args.get("question")
        if not question:
            return ToolExecutionResult("error", "Missing 'question' argument")
        return ToolExecutionResult(
            "user_question",
            question,
            {
                "question": question,
                "options": args.get("options", []),
                "context": args.get("context", ""),
            },
        )

    async def handle_propose_plan(self, args: Dict[str, Any]) -> ToolExecutionResult:
        title = args.get("title")
        objective = args.get("objective")
        tasks = args.get("tasks", [])
        if not title or not objective:
            return ToolExecutionResult("error", "Missing 'title' or 'objective'")
        if not tasks:
            return ToolExecutionResult("error", "Plan must include at least one task")
        for idx, task in enumerate(tasks):
            if not isinstance(task, dict):
                return ToolExecutionResult("error", f"Task {idx} is not a valid object")
            if not task.get("id") or not task.get("title"):
                return ToolExecutionResult("error", f"Task {idx} missing 'id' or 'title'")
            if not task.get("agent_rationale"):
                return ToolExecutionResult(
                    "error",
                    f"Task {task.get('id')} missing 'agent_rationale' (explain WHY you chose this profile)",
                )
        try:
            canonical_plan = TaskDescriptorService.canonicalize_plan_data(
                {"title": title, "objective": objective, "tasks": tasks}
            )
        except Exception as exc:
            return ToolExecutionResult("error", f"Invalid plan proposal: {exc}")
        for task in canonical_plan.get("tasks", []):
            if not task.get("agent_preset"):
                return ToolExecutionResult(
                    "error",
                    f"Task {task.get('id')} must include 'agent_preset'; legacy mood hints are accepted only for read compatibility",
                )
        return ToolExecutionResult(
            "plan_proposed",
            f"Proposed plan: {title}",
            canonical_plan,
        )

    async def handle_request_context(self, args: Dict[str, Any]) -> ToolExecutionResult:
        description = args.get("description")
        if not description:
            return ToolExecutionResult("error", "Missing 'description' argument")
        
        if not self.session_id:
            return ToolExecutionResult(
                "error", 
                "Context requests require an active App session. "
                "The current thread is not associated with a session."
            )
        
        try:
            from ...services.context_request_service import ContextRequestService
            request = ContextRequestService.create_request(
                self.session_id, 
                description, 
                args.get("metadata")
            )
            return ToolExecutionResult(
                "context_request_pending",
                f"Context request created: {description}",
                {"request_id": request["id"], "description": description}
            )
        except Exception as exc:
            logger.exception("Error creating context request")
            return ToolExecutionResult("error", f"Failed to create context request: {exc}")

    async def handle_web_search(self, args: Dict[str, Any]) -> ToolExecutionResult:
        query = args.get("query")
        if not query:
            return ToolExecutionResult("error", "Missing 'query' argument")
        if self._contract.network_mode == "blocked":
            return ToolExecutionResult("error", f"Execution policy '{self.execution_policy}' blocks network access")

        try:
            from ...models.web_search import WebSearchQuery
            from ...services.web_search_service import WebSearchService

            provider_list = args.get("providers") or ["duckduckgo"]
            if isinstance(provider_list, str):
                provider_list = [provider.strip() for provider in provider_list.split(",") if provider.strip()]
            request = WebSearchQuery(
                query=str(query),
                max_results=min(int(args.get("max_results", 5) or 5), 50),
                providers=provider_list or ["duckduckgo"],
            )
            response = await WebSearchService.search(request)
            results = [result.model_dump() for result in response.results]
            filtered = self._filter_web_results(results)
            formatted = "\n\n".join(
                [
                    f"[{idx + 1}] {item.get('title', 'Untitled')}\n{item.get('snippet', '')}\nURL: {item.get('url', '')}"
                    for idx, item in enumerate(filtered[:5])
                ]
            )
            return ToolExecutionResult(
                "success",
                f"Found {len(filtered)} results for: {query}",
                {
                    "query": str(query),
                    "results": filtered,
                    "formatted": formatted,
                    "providers_used": list(response.providers_used),
                },
            )
        except ImportError:
            logger.warning("WebSearchService not available, returning placeholder")
            return ToolExecutionResult(
                "success",
                f"[Web search placeholder] Query: {query}",
                {
                    "query": str(query),
                    "results": [],
                    "note": "Web search not configured. Install a web search provider to enable this feature.",
                },
            )
        except Exception as exc:
            logger.exception("Error in web_search for query: %s", query)
            return ToolExecutionResult("error", f"Web search failed: {exc}")
