import pytest
from pathlib import Path
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.config import REPO_ROOT_DIR

def test_operator_status_snapshot_unico_backend_authored(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    from tools.gimo_server.services.providers.service_impl import ProviderService
    from tools.gimo_server.services.conversation_service import ConversationService
    from tools.gimo_server.models import ProviderRolesConfig, ProviderRoleBinding, ProviderConfig, GimoThread, GimoTurn
    
    def mock_get_current_branch(base_dir):
        return "main"
        
    def mock_get_changed_files(base_dir):
        return ["file1.py"]
        
    def mock_get_config():
        return ProviderConfig(
            active="openai",
            providers={},
            roles=ProviderRolesConfig(
                orchestrator=ProviderRoleBinding(provider_id="openai", model="gpt-4o")
            )
        )
        
    def mock_list_threads(*args, **kwargs):
        thread = GimoThread(
            id="t-123",
            workspace_root="/tmp",
            turns=[GimoTurn(id="turn-1", agent_id="cli")],
            metadata={
                "permissions": "full-auto",
                "effort": "high",
                "workspace_mode": "source_repo",
                "orchestrator_authority": "gimo",
            },
        )
        return [thread]
        
    monkeypatch.setattr(GitService, "get_current_branch", mock_get_current_branch)
    monkeypatch.setattr(GitService, "get_changed_files", mock_get_changed_files)
    monkeypatch.setattr(ProviderService, "get_config", mock_get_config)
    monkeypatch.setattr(ConversationService, "list_threads", mock_list_threads)
    
    snapshot = OperatorStatusService.get_status_snapshot()
    
    assert snapshot["branch"] == "main"
    assert snapshot["dirty_files"] == ["file1.py"]
    assert snapshot["active_provider"] == "openai"
    assert snapshot["active_model"] == "gpt-4o"
    assert snapshot["last_thread"] == "t-123"
    assert snapshot["last_turn"] == "turn-1"
    assert snapshot["permissions"] == "full-auto"
    assert snapshot["effort"] == "high"
    assert snapshot["workspace_mode"] == "source_repo"
    assert snapshot["orchestrator_authority"] == "gimo"
    assert snapshot["backend_status"] == "ok"
    assert "alerts" in snapshot
    assert "active_run" not in snapshot


def test_operator_status_snapshot_ignores_conflicting_legacy_provider_fields(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    from tools.gimo_server.services.providers.service_impl import ProviderService
    from tools.gimo_server.services.conversation_service import ConversationService
    from tools.gimo_server.models import ProviderRolesConfig, ProviderRoleBinding, ProviderConfig

    monkeypatch.setattr(GitService, "get_current_branch", lambda _base_dir: "main")
    monkeypatch.setattr(GitService, "get_changed_files", lambda _base_dir: [])
    monkeypatch.setattr(ConversationService, "list_threads", lambda *args, **kwargs: [])

    def mock_get_config():
        return ProviderConfig(
            active="legacy-active",
            providers={},
            roles=ProviderRolesConfig(
                orchestrator=ProviderRoleBinding(provider_id="openai-main", model="gpt-5.4"),
                workers=[],
            ),
            orchestrator_provider="legacy-provider",
            orchestrator_model="legacy-model",
        )

    monkeypatch.setattr(ProviderService, "get_config", mock_get_config)

    snapshot = OperatorStatusService.get_status_snapshot()

    assert snapshot["active_provider"] == "openai-main"
    assert snapshot["active_model"] == "gpt-5.4"


def test_operator_status_snapshot_partial_on_git_failure(monkeypatch):
    from tools.gimo_server.services.git_service import GitService

    def mock_fail(*args, **kwargs):
        raise ValueError("Simulated failure")

    monkeypatch.setattr(GitService, "get_current_branch", mock_fail)

    # Defensive: get_status_snapshot catches exceptions and returns partial snapshot
    snapshot = OperatorStatusService.get_status_snapshot()
    assert isinstance(snapshot, dict)
    # Git fields should be absent or None since they failed
    assert snapshot.get("branch") is None


def test_operator_status_snapshot_includes_canonical_ui_fields(monkeypatch):
    from tools.gimo_server.services.file_service import FileService
    from tools.gimo_server.services.system_service import SystemService

    monkeypatch.setattr(
        "tools.gimo_server.services.operator_status_service.get_active_repo_dir",
        lambda: Path.cwd(),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.operator_status_service.get_allowed_paths",
        lambda _base_dir: {Path.cwd() / "a.py", Path.cwd() / "b.py"},
    )
    monkeypatch.setattr(FileService, "tail_audit_lines", lambda limit=1: ["audit line"])
    monkeypatch.setattr(SystemService, "get_status", lambda: "RUNNING")
    monkeypatch.setattr(
        "tools.gimo_server.services.operator_status_service.ALLOWLIST_REQUIRE",
        True,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.operator_status_service.time.time",
        lambda: 150.0,
    )

    snapshot = OperatorStatusService.get_status_snapshot(app_start_time=100.0)

    assert snapshot["backend_version"]
    assert snapshot["uptime_seconds"] == 50.0
    assert snapshot["allowlist_count"] == 2
    assert snapshot["last_audit_line"] == "audit line"
    assert snapshot["service_status"] == "RUNNING"
