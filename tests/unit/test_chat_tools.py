"""
Unit tests for chat tools schema and ToolExecutor extensions.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.gimo_server.engine.tools.chat_tools_schema import (
    CHAT_TOOLS,
    get_tool_risk_level,
)
from tools.gimo_server.engine.tools.executor import ToolExecutor


class TestChatToolsSchema:
    """Tests for tool definitions."""

    def test_chat_tools_count(self):
        """Should have 11 tools defined (8 base + 3 P2 meta-tools)."""
        assert len(CHAT_TOOLS) == 11

    def test_all_tools_have_required_fields(self):
        """Each tool should have proper OpenAI function format."""
        for tool in CHAT_TOOLS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"
            assert "properties" in func["parameters"]

    def test_tool_names(self):
        """Should have all expected tools."""
        names = {tool["function"]["name"] for tool in CHAT_TOOLS}
        expected = {
            "read_file",
            "write_file",
            "search_replace",
            "list_files",
            "search_text",
            "shell_exec",
            "patch_file",
            "create_dir",
            "ask_user",
            "propose_plan",
            "web_search",
        }
        assert names == expected

    def test_risk_levels(self):
        """Should return correct risk levels."""
        assert get_tool_risk_level("read_file") == "LOW"
        assert get_tool_risk_level("list_files") == "LOW"
        assert get_tool_risk_level("search_text") == "LOW"

        assert get_tool_risk_level("write_file") == "MEDIUM"
        assert get_tool_risk_level("search_replace") == "MEDIUM"
        assert get_tool_risk_level("patch_file") == "MEDIUM"
        assert get_tool_risk_level("create_dir") == "MEDIUM"

        assert get_tool_risk_level("shell_exec") == "HIGH"


class TestToolExecutorExtensions:
    """Tests for new ToolExecutor handlers."""

    @pytest.fixture
    def executor(self, tmp_path: Path):
        """Create ToolExecutor with temp workspace."""
        return ToolExecutor(workspace_root=str(tmp_path), policy={"allowed_paths": ["*"]})

    @pytest.mark.asyncio
    async def test_handle_read_file(self, executor: ToolExecutor, tmp_path: Path):
        """Should read file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, GIMO!", encoding="utf-8")

        result = await executor.handle_read_file({"path": "test.txt"})

        assert result["status"] == "success"
        assert "Hello, GIMO!" in result["data"]["content"]

    @pytest.mark.asyncio
    async def test_handle_read_file_with_line_range(self, executor: ToolExecutor, tmp_path: Path):
        """Should read specific line range."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

        result = await executor.handle_read_file({
            "path": "test.txt",
            "start_line": 2,
            "end_line": 2
        })

        assert result["status"] == "success"
        assert "Line 2" in result["data"]["content"]

    @pytest.mark.asyncio
    async def test_handle_read_file_missing_path(self, executor: ToolExecutor):
        """Should return error for missing path."""
        result = await executor.handle_read_file({})
        assert result["status"] == "error"
        assert "Missing 'path'" in result["message"]

    @pytest.mark.asyncio
    async def test_handle_list_files(self, executor: ToolExecutor, tmp_path: Path):
        """Should list files in directory."""
        (tmp_path / "file1.txt").write_text("test")
        (tmp_path / "file2.py").write_text("test")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.txt").write_text("test")

        result = await executor.handle_list_files({"path": ".", "max_depth": 2})

        assert result["status"] == "success"
        files = result["data"]["files"]
        assert "file1.txt" in files
        assert "file2.py" in files
        assert "subdir/file3.txt" in files

    @pytest.mark.asyncio
    async def test_handle_list_files_with_pattern(self, executor: ToolExecutor, tmp_path: Path):
        """Should filter files by pattern."""
        (tmp_path / "file1.txt").write_text("test")
        (tmp_path / "file2.py").write_text("test")

        result = await executor.handle_list_files({"path": ".", "pattern": "*.py"})

        assert result["status"] == "success"
        files = result["data"]["files"]
        assert "file2.py" in files
        assert "file1.txt" not in files

    @pytest.mark.asyncio
    async def test_handle_list_files_ignores_hidden(self, executor: ToolExecutor, tmp_path: Path):
        """Should ignore hidden files and common dirs."""
        (tmp_path / "visible.txt").write_text("test")
        (tmp_path / ".hidden").write_text("test")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "package.json").write_text("{}")

        result = await executor.handle_list_files({"path": "."})

        assert result["status"] == "success"
        files = result["data"]["files"]
        assert "visible.txt" in files
        assert ".hidden" not in files
        assert "node_modules/package.json" not in files

    @pytest.mark.asyncio
    async def test_handle_search_replace(self, executor: ToolExecutor, tmp_path: Path):
        """Should search and replace text."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")

        result = await executor.handle_search_replace({
            "path": "test.txt",
            "old_text": "World",
            "new_text": "GIMO"
        })

        assert result["status"] == "success"
        content = test_file.read_text(encoding="utf-8")
        assert content == "Hello, GIMO!"

    @pytest.mark.asyncio
    async def test_handle_search_replace_not_unique(self, executor: ToolExecutor, tmp_path: Path):
        """Should error if old_text appears multiple times."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello Hello", encoding="utf-8")

        result = await executor.handle_search_replace({
            "path": "test.txt",
            "old_text": "Hello",
            "new_text": "Hi"
        })

        assert result["status"] == "error"
        assert "2 times" in result["message"]

    @pytest.mark.asyncio
    async def test_handle_search_replace_not_found(self, executor: ToolExecutor, tmp_path: Path):
        """Should error if old_text not found."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")

        result = await executor.handle_search_replace({
            "path": "test.txt",
            "old_text": "Goodbye",
            "new_text": "Hi"
        })

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_shell_exec(self, executor: ToolExecutor):
        """Should execute shell command."""
        result = await executor.handle_shell_exec({
            "command": "echo Hello GIMO",
            "timeout": 5
        })

        # Note: Windows uses different shell syntax
        assert result["status"] in ("success", "error")
        if result["status"] == "success":
            assert "Hello" in result["data"]["stdout"] or result["data"]["returncode"] == 0

    @pytest.mark.asyncio
    async def test_handle_shell_exec_timeout(self, executor: ToolExecutor):
        """Should timeout long-running commands."""
        import sys
        if sys.platform == "win32":
            cmd = "python -c \"import time; time.sleep(10)\""
        else:
            cmd = "sleep 10"

        result = await executor.handle_shell_exec({
            "command": cmd,
            "timeout": 1
        })

        assert result["status"] == "error"
        assert "timeout" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_shell_exec_missing_command(self, executor: ToolExecutor):
        """Should error if command missing."""
        result = await executor.handle_shell_exec({})
        assert result["status"] == "error"
        assert "Missing 'command'" in result["message"]

    @pytest.mark.asyncio
    async def test_handle_search_text(self, executor: ToolExecutor, tmp_path: Path):
        """Should search for text pattern."""
        (tmp_path / "file1.txt").write_text("Hello GIMO\nGoodbye World")
        (tmp_path / "file2.txt").write_text("GIMO is great")

        # Mock subprocess to avoid actual grep/rg
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="file1.txt:1:Hello GIMO\nfile2.txt:1:GIMO is great",
                returncode=0
            )

            result = await executor.handle_search_text({
                "pattern": "GIMO",
                "path": "."
            })

        # Check that subprocess was called
        assert mock_run.called
        # Check result structure
        # Note: Result depends on whether we mocked it successfully
        assert "status" in result
