import pytest
from tools.gimo_server.services.thread_session_service import ThreadSessionService
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService
from tools.gimo_server.services.conversation_service import ConversationService
from tools.gimo_server.ops_models import GimoThread

def test_thread_reset_clears_context_not_identity(tmp_path):
    # Setup
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    
    # Add context directly
    thread_id = thread.id
    ThreadSessionService.add_context(thread_id, {"file": "main.py"})
    
    # Verify added
    t1 = ConversationService.get_thread(thread_id)
    assert t1.metadata.get("context") == [{"file": "main.py"}]
    
    # Reset
    res = ThreadSessionService.reset_thread(thread_id)
    assert res is True
    
    # Verify cleared but identity remains
    t2 = ConversationService.get_thread(thread_id)
    assert t2 is not None
    assert t2.id == thread_id
    assert t2.metadata.get("context") == []

def test_thread_config_updates_effort_and_permissions(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    thread_id = thread.id

    res = ThreadSessionService.update_config(thread_id, {"effort": "high", "permissions": "read-write"})
    assert res is True

    t1 = ConversationService.get_thread(thread_id)
    assert t1.metadata.get("effort") == "high"
    assert t1.metadata.get("permissions") == "read-write"

def test_context_add_persists_attached_file(tmp_path):
    ConversationService.THREADS_DIR = tmp_path
    thread = ConversationService.create_thread(workspace_root="/tmp/test", title="Test Thread")
    thread_id = thread.id

    res = ThreadSessionService.add_context(thread_id, {"type": "file", "path": "docs/architecture.md"})
    assert res is True

    t1 = ConversationService.get_thread(thread_id)
    ctx = t1.metadata.get("context")
    assert len(ctx) == 1
    assert ctx[0]["path"] == "docs/architecture.md"

def test_operator_status_returns_single_snapshot():
    snapshot = OperatorStatusService.get_status_snapshot()
    # verify expected fields are present (can be null/default but must exist)
    expected_fields = [
        "repo", "branch", "dirty_files", "active_provider",
        "active_model", "permission_mode", "backend_status",
        "backend_version", "active_run", "active_stage",
        "budget_spend", "budget_limit", "context_percentage",
        "last_thread", "last_turn", "alerts"
    ]
    for ef in expected_fields:
        assert ef in snapshot
    
    # Explicit default validations
    assert snapshot["backend_status"] == "online"
    assert isinstance(snapshot["dirty_files"], list)

def test_notice_policy_ctx_warning():
    notices = NoticePolicyService.evaluate_all({"context_percentage": 75.0})
    warning_found = False
    for n in notices:
        if n["code"] == "ctx_high" and n["level"] == "warning":
            warning_found = True
    assert warning_found

def test_notice_policy_budget_warning():
    notices = NoticePolicyService.evaluate_all({"budget_percentage": 85.0})
    warning_found = False
    for n in notices:
        if n["code"] == "budget_high" and n["level"] == "warning":
            warning_found = True
    assert warning_found
