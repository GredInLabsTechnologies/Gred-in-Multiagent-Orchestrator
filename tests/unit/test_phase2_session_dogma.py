import pytest
from tools.gimo_server.services.thread_session_service import ThreadSessionService
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService
from tools.gimo_server.services.conversation_service import ConversationService
from tools.gimo_server.ops_models import GimoThread

def test_thread_reset_clears_context_and_attached_files(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    
    thread_id = thread.id
    ThreadSessionService.add_context(thread_id, {"type": "file", "path": "main.py"})
    
    t1 = ConversationService.get_thread(thread_id)
    assert len(t1.metadata.get("context", [])) == 1
    assert len(t1.metadata.get("attached_files", [])) == 1
    
    res = ThreadSessionService.reset_thread(thread_id)
    assert res is True
    
    t2 = ConversationService.get_thread(thread_id)
    assert t2.id == thread_id
    assert t2.metadata.get("context") == []
    assert t2.metadata.get("attached_files") == []

def test_thread_config_updates_effort_and_permissions(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    thread_id = thread.id

    ThreadSessionService.update_config(thread_id, {"effort": "high", "permissions": "read-write"})
    
    t1 = ConversationService.get_thread(thread_id)
    assert t1.metadata.get("effort") == "high"
    assert t1.metadata.get("permissions") == "read-write"

def test_context_add_persists_attached_file(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    thread_id = thread.id

    ThreadSessionService.add_context(thread_id, {"type": "file", "path": "docs/architecture.md"})
    
    t1 = ConversationService.get_thread(thread_id)
    ctx = t1.metadata.get("context")
    attached = t1.metadata.get("attached_files")
    assert len(ctx) == 1
    assert ctx[0]["path"] == "docs/architecture.md"
    assert len(attached) == 1
    assert attached[0]["path"] == "docs/architecture.md"

def test_get_usage_explains_absence_if_not_authoritative(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test")
    thread_id = thread.id
    
    usage = ThreadSessionService.get_usage(thread_id)
    assert usage is not None
    assert usage.get("authoritative") is False
    assert "reason" in usage

def test_operator_status_reads_real_backend_sources(monkeypatch):
    from tools.gimo_server.services.git_service import GitService
    def mock_get_current_branch(*args): return "feature/test-branch"
    def mock_get_changed_files(*args): return ["a.py", "b.py"]
    monkeypatch.setattr(GitService, "get_current_branch", mock_get_current_branch)
    monkeypatch.setattr(GitService, "get_changed_files", mock_get_changed_files)
    
    from tools.gimo_server.services.provider_service_impl import ProviderService
    class MockRole:
        provider_id = "test-provider"
        model = "test-model"
        permission_mode = "admin"
    class MockRoles:
        orchestrator = MockRole()
    class MockConfig:
        roles = MockRoles()
    monkeypatch.setattr(ProviderService, "get_config", lambda: MockConfig())
    
    from tools.gimo_server.services.notice_policy_service import NoticePolicyService
    def mock_evaluate_all(*args): return [{"level": "info", "message": "mock alert"}]
    monkeypatch.setattr(NoticePolicyService, "evaluate_all", mock_evaluate_all)
    
    snapshot = OperatorStatusService.get_status_snapshot()
    
    assert snapshot["branch"] == "feature/test-branch"
    assert snapshot["dirty_files"] == ["a.py", "b.py"]
    assert snapshot["active_provider"] == "test-provider"
    assert snapshot["active_model"] == "test-model"
    assert snapshot["permission_mode"] == "admin"
    assert snapshot["alerts"] == [{"level": "info", "message": "mock alert"}]

def test_notice_policy_budget_percentage_calculation():
    notices = NoticePolicyService.evaluate_all({"budget_spend": 85.0, "budget_limit": 100.0})
    warning_found = False
    for n in notices:
        if n["code"] == "budget_high" and n["level"] == "warning":
            warning_found = True
            assert "85.0%" in n["message"]
    assert warning_found
