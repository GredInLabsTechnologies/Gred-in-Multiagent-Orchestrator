import pytest
from pathlib import Path
from tools.gimo_server.services.thread_session_service import ThreadSessionService
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService
from tools.gimo_server.services.conversation_service import ConversationService
from tools.gimo_server.config import REPO_ROOT_DIR

def test_thread_reset_clears_context_and_attached_files(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="test")
    
    ThreadSessionService.add_context(thread.id, {"type": "file", "path": "main.py"})
    
    res = ThreadSessionService.reset_thread(thread.id)
    assert res is True
    
    t2 = ConversationService.get_thread(thread.id)
    assert t2.metadata.get("context") == []
    assert t2.metadata.get("attached_files") == []

def test_context_add_persists_attached_file(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="test")

    ThreadSessionService.add_context(thread.id, {"type": "file", "path": "docs.md"})
    
    t1 = ConversationService.get_thread(thread.id)
    attached = t1.metadata.get("attached_files")
    assert len(attached) == 1
    assert attached[0]["path"] == "docs.md"


def test_thread_config_persists_workspace_mode(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="test")

    res = ThreadSessionService.update_config(thread.id, {"workspace_mode": "source_repo"})

    assert res is True
    updated = ConversationService.get_thread(thread.id)
    assert updated.metadata["workspace_mode"] == "source_repo"


def test_thread_creation_sets_backend_authored_surface_and_orchestrator(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="test")

    assert thread.metadata["surface"] == "operator"
    assert thread.metadata["orchestrator_authority"] == "gimo"
    assert thread.metadata["orchestrator_selection_allowed"] is True
    assert thread.metadata["worker_model_selection_allowed"] is True


def test_thread_config_rejects_orchestrator_override(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="test")

    with pytest.raises(ValueError, match="backend-controlled"):
        ThreadSessionService.update_config(thread.id, {"orchestrator_authority": "chatgpt_app"})

    with pytest.raises(ValueError, match="backend-controlled"):
        ThreadSessionService.update_config(thread.id, {"worker_model_selection_allowed": False})

def test_get_usage_explains_absence_if_not_authoritative(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="Test")
    
    usage = ThreadSessionService.get_usage(thread.id)
    assert "authoritative" not in usage, "Debe rechazar authoritative"
    assert "reason" not in usage, "Debe rechazar reason"
    assert "null" not in usage, "Debe rechazar nul o stubs"
    assert usage == {}

def test_operator_status_reads_real_backend_sources_and_avoids_stubs(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    def mock_get_current_branch(base_dir): 
        assert base_dir == Path(REPO_ROOT_DIR)  # STRICTLY VERIFY REPO_ROOT_DIR IS USED, NOT CWD
        return "feature/test-branch"
    def mock_get_changed_files(base_dir): return ["a.py"]
    monkeypatch.setattr(GitService, "get_current_branch", mock_get_current_branch)
    monkeypatch.setattr(GitService, "get_changed_files", mock_get_changed_files)
    
    snapshot = OperatorStatusService.get_status_snapshot()
    
    assert snapshot["branch"] == "feature/test-branch"

    # Verify the snapshot is backend-authored and avoids fake aggregated stubs.
    assert snapshot["backend_status"] == "ok"
    assert "active_run" not in snapshot
    assert "context_percentage" not in snapshot
    assert snapshot["dirty_files"] == ["a.py"]

def test_notice_policy_budget_percentage_handles_missing_fields():
    notices = NoticePolicyService.evaluate_all({})
    warning_codes = [n["code"] for n in notices]
    assert "budget_high" not in warning_codes

def test_notice_policy_budget_percentage_calculation():
    notices = NoticePolicyService.evaluate_all({"budget_spend": 85.0, "budget_limit": 100.0})
    assert any(n["code"] == "budget_high" for n in notices)
