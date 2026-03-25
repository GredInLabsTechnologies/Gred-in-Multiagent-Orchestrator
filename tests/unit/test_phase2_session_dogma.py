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

def test_get_usage_explains_absence_if_not_authoritative(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp", title="Test")
    
    usage = ThreadSessionService.get_usage(thread.id)
    assert usage.get("authoritative") is False

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
    
    # Assert explicit non-authoritative objects instead of stubs
    assert isinstance(snapshot["backend_status"], dict)
    assert snapshot["backend_status"].get("authoritative") is False
    
    assert isinstance(snapshot["active_run"], dict)
    assert snapshot["active_run"].get("authoritative") is False

    assert isinstance(snapshot["budget_spend"], dict)
    assert snapshot["budget_spend"].get("authoritative") is False

def test_notice_policy_budget_percentage_survives_dict_values():
    notices = NoticePolicyService.evaluate_all({
        "budget_spend": {"authoritative": False},
        "budget_limit": {"authoritative": False}
    })
    warning_codes = [n["code"] for n in notices]
    assert "budget_high" not in warning_codes

def test_notice_policy_budget_percentage_calculation():
    notices = NoticePolicyService.evaluate_all({"budget_spend": 85.0, "budget_limit": 100.0})
    assert any(n["code"] == "budget_high" for n in notices)
