import pytest
from pathlib import Path
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.config import REPO_ROOT_DIR

def test_operator_status_snapshot_unico_backend_authored(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    from tools.gimo_server.services.provider_service_impl import ProviderService
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
        thread = GimoThread(id="t-123", workspace_root="/tmp", turns=[GimoTurn(id="turn-1", agent_id="cli")])
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
    assert "alerts" in snapshot
    
    # Asserting no fake fields
    assert "budget_spend" not in snapshot
    assert "active_run" not in snapshot

def test_operator_status_snapshot_strict_failure(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    from tools.gimo_server.services.provider_service_impl import ProviderService
    from tools.gimo_server.services.conversation_service import ConversationService
    
    def mock_fail(*args, **kwargs):
        raise ValueError("Simulated failure")
        
    monkeypatch.setattr(GitService, "get_current_branch", mock_fail)
    
    with pytest.raises(ValueError, match="Simulated failure"):
        OperatorStatusService.get_status_snapshot()
