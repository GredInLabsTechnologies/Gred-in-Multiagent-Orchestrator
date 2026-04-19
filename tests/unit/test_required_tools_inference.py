"""BUGS_LATENTES §H2 — inferencia de required_tools.

Antes del fix el campo era dead (`required_tools=[]` hardcoded). Ahora
`TaskDescriptorService._infer_required_tools` popular con defaults por
task_type + hints por token en el text.
"""
from __future__ import annotations

import pytest

from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


def _descriptor_text(title: str = "", description: str = "", role: str = "") -> dict:
    return {
        "title": title,
        "description": description,
        "requested_role": role,
    }


def test_security_review_gets_scanner_tools():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(title="Security audit of auth flow")
    )
    assert d.task_type == "security_review"
    assert "security_scanner" in d.required_tools
    assert "code_reader" in d.required_tools


def test_research_task_gets_search_tools():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(
            title="Research best Python ORM",
            description="Investigate options for analysis",
        )
    )
    assert d.task_type == "research"
    assert "web_search" in d.required_tools
    assert "doc_reader" in d.required_tools


def test_orchestrator_gets_plan_tools():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(title="Orchestrate the delivery plan")
    )
    assert d.task_type == "orchestrator"
    assert "plan_editor" in d.required_tools


def test_execution_task_gets_fs_and_shell():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(title="Implement new endpoint")
    )
    assert d.task_type == "execution"
    assert "file_writer" in d.required_tools
    assert "shell_exec" in d.required_tools


def test_token_hint_adds_extra_tools():
    """Text con 'pytest' → añade test_runner además del default."""
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(
            title="Fix failing pytest tests",
            description="Update the test suite",
        )
    )
    assert "test_runner" in d.required_tools


def test_token_hint_git_ops():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(
            title="Rebase feature branch",
            description="git commit cleanup",
        )
    )
    assert "git_ops" in d.required_tools


def test_tools_deduped():
    """Si task_type default + token hint convergen al mismo tool, no duplica."""
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(
            title="Patch this file please",
            description="refactor",
        )
    )
    # execution gives file_writer; hint "patch"/"refactor" also yields file_writer
    assert d.required_tools.count("file_writer") == 1


def test_human_gate_tool():
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(title="Ask approval for release")
    )
    assert d.task_type == "human_gate"
    assert "hitl_gate" in d.required_tools


def test_required_tools_never_none():
    """Tasks vacíos retornan lista (no None)."""
    d = TaskDescriptorService.descriptor_from_task(_descriptor_text())
    assert isinstance(d.required_tools, list)


def test_tool_names_are_stable_strings():
    """Cada tool name es un string non-empty, no object."""
    d = TaskDescriptorService.descriptor_from_task(
        _descriptor_text(
            title="Review security of auth",
            description="test pytest ensure",
        )
    )
    for tool in d.required_tools:
        assert isinstance(tool, str)
        assert tool.strip() == tool
        assert " " not in tool  # convención snake_case_sin_espacios
