from __future__ import annotations

import json

import pytest

from tools.gimo_server.engine.contracts import StageInput
from tools.gimo_server.engine.stages.file_write import FileWrite


@pytest.fixture
def stage() -> FileWrite:
    return FileWrite()


@pytest.mark.asyncio
async def test_file_write_passes_explicit_execution_policy_from_context(monkeypatch, tmp_path, stage: FileWrite):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, *, workspace_root: str, policy: dict[str, object], execution_policy: str, **_: object):
            captured["workspace_root"] = workspace_root
            captured["policy"] = policy
            captured["execution_policy"] = execution_policy

        async def execute_tool_call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            captured["tool_name"] = name
            captured["arguments"] = arguments
            return {"status": "success", "message": "ok", "data": {}}

    monkeypatch.setattr("tools.gimo_server.engine.stages.file_write.ToolExecutor", FakeExecutor)

    result = await stage.execute(
        StageInput(
            run_id="run-file-write-explicit",
            context={
                "workspace_root": str(tmp_path),
                "execution_policy": "read_only",
                "allowed_paths": ["note.txt"],
            },
            artifacts={
                "llm_response": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "note.txt", "content": "hello"}),
                            }
                        }
                    ]
                }
            },
        )
    )

    assert result.status == "continue"
    assert captured["execution_policy"] == "read_only"
    assert captured["policy"] == {"allowed_paths": ["note.txt"]}
    assert captured["tool_name"] == "write_file"


@pytest.mark.asyncio
async def test_file_write_defaults_to_workspace_safe_without_explicit_policy(monkeypatch, tmp_path, stage: FileWrite):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, *, execution_policy: str, **_: object):
            captured["execution_policy"] = execution_policy

        async def execute_tool_call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            return {"status": "success", "message": "ok", "data": {"name": name, "arguments": arguments}}

    monkeypatch.setattr("tools.gimo_server.engine.stages.file_write.ToolExecutor", FakeExecutor)

    result = await stage.execute(
        StageInput(
            run_id="run-file-write-default",
            context={
                "workspace_root": str(tmp_path),
                "allowed_paths": ["note.txt"],
            },
            artifacts={
                "llm_response": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "note.txt", "content": "hello"}),
                            }
                        }
                    ]
                }
            },
        )
    )

    assert result.status == "continue"
    assert captured["execution_policy"] == "workspace_safe"


@pytest.mark.asyncio
async def test_file_write_reads_explicit_policy_from_gen_context(monkeypatch, tmp_path, stage: FileWrite):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, *, execution_policy: str, policy: dict[str, object], **_: object):
            captured["execution_policy"] = execution_policy
            captured["policy"] = policy

        async def execute_tool_call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            return {"status": "success", "message": "ok", "data": {"name": name, "arguments": arguments}}

    monkeypatch.setattr("tools.gimo_server.engine.stages.file_write.ToolExecutor", FakeExecutor)

    result = await stage.execute(
        StageInput(
            run_id="run-file-write-gen-context",
            context={
                "workspace_root": str(tmp_path),
                "gen_context": {
                    "policy": {"allowed_paths": ["note.txt"]},
                    "execution_policy": "workspace_experiment",
                },
            },
            artifacts={
                "llm_response": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "note.txt", "content": "hello"}),
                            }
                        }
                    ]
                }
            },
        )
    )

    assert result.status == "continue"
    assert captured["execution_policy"] == "workspace_experiment"
    assert captured["policy"] == {"allowed_paths": ["note.txt"]}
