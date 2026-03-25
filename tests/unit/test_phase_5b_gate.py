import pytest
import json
import asyncio
import os
from unittest.mock import MagicMock, patch
from tools.gimo_server.models.core import OpsRun, OpsApproved
from tools.gimo_server.schemas.draft_validation import ValidatedTaskSpec
from tools.gimo_server.services.run_worker import RunWorker
from tools.gimo_server.services.ops.ops_service import OpsService
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.provider_service_impl import ProviderService
from tools.gimo_server.engine.tools.executor import ToolExecutor, ToolExecutionResult
from tools.gimo_server.engine.moods import MoodProfile, MoodContract

def _persist_approved_stub(approved: OpsApproved):
    path = OpsService._approved_path(approved.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(approved.model_dump_json(), encoding="utf-8")

@pytest.fixture
def mock_ops_service(tmp_path):
    # Setup OpsService for isolated test
    OpsService._ROOT_DIR = tmp_path
    OpsService.OPS_DIR = tmp_path
    OpsService.DRAFTS_DIR = tmp_path / "drafts"
    OpsService.APPROVED_DIR = tmp_path / "approved"
    OpsService.RUNS_DIR = tmp_path / "runs"
    OpsService.RUN_EVENTS_DIR = tmp_path / "run_events"
    OpsService.RUN_LOGS_DIR = tmp_path / "run_logs"
    OpsService.LOCKS_DIR = tmp_path / "locks"
    OpsService.LOCK_FILE = tmp_path / ".ops.lock"
    OpsService.ensure_dirs()
    return OpsService

@pytest.mark.asyncio
async def test_no_run_without_validated_task_spec(mock_ops_service):
    # Mock approved
    appr = OpsApproved(id="appr_1", draft_id="d_1", content="test", prompt="test")
    _persist_approved_stub(appr)
    
    run = mock_ops_service.create_run(appr.id)
    # Ensure it's not set
    run_meta = mock_ops_service.get_run(run.id)
    run_meta.validated_task_spec = None
    mock_ops_service._persist_run(run_meta)
    
    worker = RunWorker()
    
    # Execute run should fail and mark it as error
    await worker._execute_run(run.id)
    
    updated_run = mock_ops_service.get_run(run.id)
    assert updated_run.status == "error"
    assert any("ValidatedTaskSpec" in entry["msg"] for entry in updated_run.log)

@pytest.mark.asyncio
async def test_worker_context_is_scoped_by_task_spec(mock_ops_service, tmp_path):
    # Setup repo
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "file1.py").write_text("content1")
    (repo_dir / "file2.py").write_text("content2")
    
    # Mock AppSessionService.get_path_from_handle
    with patch.object(AppSessionService, 'get_path_from_handle', return_value=str(repo_dir)):
        # Create run with task spec
        appr = OpsApproved(id="appr_2", draft_id="d_2", content="test", prompt="test")
        _persist_approved_stub(appr)
        
        run = mock_ops_service.create_run(appr.id)
        run.validated_task_spec = {
            "base_commit": "HEAD",
            "repo_handle": "h_repo",
            "allowed_paths": ["file1.py"],
            "acceptance_criteria": "test passes",
            "evidence_hash": "h1",
            "context_pack_id": "cp_1",
            "worker_model": "gpt-4",
            "requires_manual_merge": True
        }
        mock_ops_service._persist_run(run)
        
        worker = RunWorker()
        
        # Mock EngineService.execute_run in the MODULE where it's defined
        with patch("tools.gimo_server.services.engine_service.EngineService.execute_run") as mock_exec:
            mock_exec.return_value = asyncio.Future()
            mock_exec.return_value.set_result({"status": "completed"})
            
            await worker._execute_run(run.id)
            
            # Re-read run to check child_context
            final_run = mock_ops_service.get_run(run.id)
            child_ctx = final_run.child_context
            
            assert child_ctx is not None
            assert "gen_context" in child_ctx
            assert "bounded_files" in child_ctx["gen_context"]
            assert "allowed_paths" in child_ctx
            assert "file1.py" in child_ctx["allowed_paths"]
            assert any(f["path"] == "file1.py" for f in child_ctx["gen_context"]["bounded_files"])

@pytest.mark.asyncio
async def test_tool_executor_request_context_workflow(tmp_path):
    # Patch the service directly
    with patch("tools.gimo_server.services.context_request_service.ContextRequestService.create_request") as mock_create:
        mock_create.return_value = {"id": "req_123"}
        
        executor = ToolExecutor(
            workspace_root=str(tmp_path),
            session_id="sess_1"
        )
        
        result = await executor.handle_request_context({"description": "Need API key"})
        
        assert result["status"] == "context_request_pending"
        assert result["data"]["request_id"] == "req_123"
        assert mock_create.called
        mock_create.assert_called_with("sess_1", "Need API key", None)

@pytest.mark.asyncio
async def test_agentic_loop_pauses_on_context_request(tmp_path):
    from tools.gimo_server.services.agentic_loop_service import AgenticLoopService
    from tools.gimo_server.providers.base import ProviderAdapter
    
    # Mock provider 
    mock_adapter = MagicMock(spec=ProviderAdapter)
    
    async def mock_chat(*args, **kwargs):
        return {
            "role": "assistant",
            "content": "I need more info",
            "tool_calls": [{
                "id": "tc_1",
                "type": "function",
                "function": {
                    "name": "request_context",
                    "arguments": json.dumps({"description": "What is the db password?"})
                }
            }],
            "usage": {"total_tokens": 100}
        }
    
    mock_adapter.chat_with_tools = MagicMock(side_effect=mock_chat)
    
    mock_mood_profile = MagicMock(spec=MoodProfile)
    mock_mood_profile.max_turns = 5
    mock_mood_profile.temperature = 0.7
    mock_mood_profile.contract = MagicMock(spec=MoodContract)
    mock_mood_profile.contract.max_cost_per_turn_usd = 0.1
    
    # Mock ContextRequestService.create_request
    with patch("tools.gimo_server.services.context_request_service.ContextRequestService.create_request") as mock_create:
        mock_create.return_value = {"id": "req_abc"}
        
        # Run loop
        result = await AgenticLoopService._run_loop(
            adapter=mock_adapter,
            provider_id="p1",
            model="m1",
            workspace_root=str(tmp_path),
            token="t1",
            mood="neutral",
            mood_profile=mock_mood_profile,
            messages=[],
            max_turns=5,
            temperature=0.7,
            tools=[],
            task_key="test",
            session_id="sess_abc" # Phase 5B
        )
        
        assert result.finish_reason == "context_request_pending"
        assert "Execution paused" in result.response

@pytest.mark.asyncio
async def test_agentic_loop_resumes_after_resolution(tmp_path):
    from tools.gimo_server.services.agentic_loop_service import AgenticLoopService, AgenticResult
    from tools.gimo_server.services.context_request_service import ContextRequestService
    from tools.gimo_server.services.conversation_service import ConversationService
    from tools.gimo_server.services.app_session_service import AppSessionService
    from tools.gimo_server.providers.base import ProviderAdapter
    from tools.gimo_server.config import get_settings
    
    session_id = f"s_{os.getpid()}_{id(tmp_path)}"
    
    # 0. Setup Paths
    sessions_dir = tmp_path / "sessions"
    threads_dir = tmp_path / "threads"
    sessions_dir.mkdir()
    threads_dir.mkdir()
    
    with patch.object(AppSessionService, "_get_sessions_dir", return_value=sessions_dir):
        with patch.object(ConversationService, "THREADS_DIR", threads_dir):
            # 1. Create a "real" session
            session = AppSessionService.create_session()
            sid = session["id"]
            
            # 2. Setup thread store for this sid
            from tools.gimo_server.ops_models import GimoThread
            thread = GimoThread(id=sid, workspace_root=str(tmp_path), title="Test")
            ConversationService.save_thread(thread)
        
            # 3. Create a pending request
            request = ContextRequestService.create_request(sid, "Need more info", {"call_id": "call_123"})
            
            # 4. Resolve the request
            ContextRequestService.resolve_request(sid, request["id"], "Here is the info: API key is XYZ")
            
            # 5. Resume the session (Hardened: Mock only adapter, not the loop)
            mock_adapter = MagicMock(spec=ProviderAdapter)
            async def mock_chat(*args, **kwargs):
                return {"role": "assistant", "content": "Got it, thanks!", "usage": {"total_tokens": 50}}
            mock_adapter.chat_with_tools = MagicMock(side_effect=mock_chat)
            
            with patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter", return_value=(mock_adapter, "p1", "m1")):
                res = await AgenticLoopService.resume_session(sid, workspace_root=str(tmp_path))
                
                assert "Got it" in res.response
                
                # Verify tool result was injected
                updated_thread = ConversationService.get_thread(sid)
                tool_results = [item for turn in updated_thread.turns for item in turn.items if item.type == "tool_result"]
                assert len(tool_results) >= 1
                assert "API key is XYZ" in tool_results[0].content
                assert tool_results[0].metadata["call_id"] == "call_123"
                
                # Verify request was marked as archived in the session after resumption
                final_session = AppSessionService.get_session(sid)
                assert final_session["context_requests"][request["id"]]["status"] == "archived"

@pytest.mark.asyncio
async def test_run_worker_rejects_malformed_validated_task_spec(mock_ops_service):
    # Missing required fields
    appr = OpsApproved(id="appr_3", draft_id="d_3", content="test", prompt="test")
    _persist_approved_stub(appr)
    run = mock_ops_service.create_run(appr.id)
    run.validated_task_spec = {
        "base_commit": "HEAD",
        # Missing repo_handle and others
    }
    mock_ops_service._persist_run(run)
    
    worker = RunWorker()
    await worker._execute_run(run.id)
    
    updated_run = mock_ops_service.get_run(run.id)
    assert updated_run.status == "error"
    assert any("Malformed TaskSpec" in entry["msg"] for entry in updated_run.log)

@pytest.mark.asyncio
async def test_worker_context_never_exceeds_max_files(mock_ops_service, tmp_path):
    repo_dir = tmp_path / "repo_max"
    repo_dir.mkdir()
    allowed = []
    for i in range(10):
        f = repo_dir / f"file{i}.py"
        f.write_text(f"def func{i}(): pass")
        allowed.append(f"file{i}.py")
        
    worker = RunWorker()
    context = worker._build_worker_context(
        task={"allowed_paths": allowed},
        repo_root=repo_dir,
        max_files=5
    )
    
    assert len(context) <= 5
    # Strict allowed_paths only (P5.4 fix verification)
    assert all(f["path"] in allowed[:5] for f in context)

@pytest.mark.asyncio
async def test_allowed_paths_survives_engine_context_merge(mock_ops_service, tmp_path):
    repo_dir = tmp_path / "repo_merge"
    repo_dir.mkdir()
    (repo_dir / "target.py").write_text("print('hello')")
    
    with patch.object(AppSessionService, 'get_path_from_handle', return_value=str(repo_dir)):
        appr = OpsApproved(id="appr_4", draft_id="d_4", content="test", prompt="test")
        _persist_approved_stub(appr)
        
        run = mock_ops_service.create_run(appr.id)
        run.validated_task_spec = {
            "base_commit": "HEAD",
            "repo_handle": "h1",
            "allowed_paths": ["target.py"],
            "acceptance_criteria": "done",
            "evidence_hash": "abc",
            "context_pack_id": "cp1",
            "worker_model": "m1",
            "requires_manual_merge": True
        }
        mock_ops_service._persist_run(run)
        
        worker = RunWorker()
        with patch("tools.gimo_server.services.engine_service.EngineService.execute_run") as mock_exec:
            await worker._execute_run(run.id)
            
            # Check session state before engine call
            final_run = mock_ops_service.get_run(run.id)
            assert final_run.child_context["allowed_paths"] == ["target.py"]

@pytest.mark.asyncio
async def test_run_stream_propagates_session_id():
    from tools.gimo_server.services.agentic_loop_service import AgenticLoopService, AgenticResult
    from tools.gimo_server.services.conversation_service import ConversationService
    from tools.gimo_server.providers.base import ProviderAdapter
    
    mock_adapter = MagicMock(spec=ProviderAdapter)
    
    with patch.object(AgenticLoopService, "reserve_thread_execution", return_value={"owner_id": "o1"}):
        with patch.object(AgenticLoopService, "release_thread_execution"):
            with patch.object(AgenticLoopService, "_start_thread_execution_heartbeat", return_value=(asyncio.Event(), MagicMock())):
                with patch.object(AgenticLoopService, "_stop_heartbeat"):
                    with patch.object(ConversationService, "get_thread", return_value=MagicMock(mood="neutral", turns=[])):
                        with patch.object(ConversationService, "add_turn", return_value=MagicMock(id="t1")):
                            with patch.object(ConversationService, "append_item"):
                                with patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter", return_value=(mock_adapter, "p1", "m1")):
                                    with patch.object(AgenticLoopService, "_run_loop") as mock_run_loop:
                                        mock_run_loop.return_value = asyncio.Future()
                                        mock_run_loop.return_value.set_result(AgenticResult(response="ok"))
                                        
                                        gen = AgenticLoopService.run_stream(
                                            thread_id="t1",
                                            user_message="hi",
                                            workspace_root="/tmp",
                                            session_id="SESS_PROPS"
                                        )
                                        async for _ in gen: pass
                                        
                                        # Verify session_id propagation
                                        args, kwargs = mock_run_loop.call_args
                                        assert kwargs["session_id"] == "SESS_PROPS"

@pytest.mark.asyncio
async def test_agentic_loop_does_not_delegate_free_recon_to_worker(mock_ops_service):
    # Worker must reject if ValidatedTaskSpec is missing (no auto-recon)
    appr = OpsApproved(id="appr_5", draft_id="d_5", content="test", prompt="test")
    _persist_approved_stub(appr)
    run = mock_ops_service.create_run(appr.id)
    # No validated_task_spec
    
    worker = RunWorker()
    await worker._execute_run(run.id)
    
    updated_run = mock_ops_service.get_run(run.id)
    assert updated_run.status == "error"
    assert any("Recon required" in entry["msg"] for entry in updated_run.log)

@pytest.mark.asyncio
async def test_execution_without_repo_context_pack_is_rejected_or_blocked(mock_ops_service):
    # If repo_handle cannot be resolved, block.
    appr = OpsApproved(id="appr_6", draft_id="d_6", content="test", prompt="test")
    _persist_approved_stub(appr)
    
    run = mock_ops_service.create_run(appr.id)
    run.validated_task_spec = {
        "base_commit": "HEAD",
        "repo_handle": "INVALID_HANDLE",
        "allowed_paths": ["f1.py"],
        "acceptance_criteria": "done",
        "evidence_hash": "abc",
        "context_pack_id": "cp1",
        "worker_model": "m1",
        "requires_manual_merge": True
    }
    mock_ops_service._persist_run(run)
    
    with patch.object(AppSessionService, 'get_path_from_handle', return_value=None):
        worker = RunWorker()
        await worker._execute_run(run.id)
        
        updated_run = mock_ops_service.get_run(run.id)
        assert updated_run.status == "error"
        assert any("repo_handle to path" in entry["msg"] for entry in updated_run.log)

@pytest.mark.asyncio
async def test_execution_with_out_of_scope_path_is_rejected(mock_ops_service, tmp_path):
    repo_dir = tmp_path / "repo_scope"
    repo_dir.mkdir()
    
    worker = RunWorker()
    # build_worker_context uses rel_path, if it escapes it returns empty/error or is blocked.
    context = worker._build_worker_context(
        task={"allowed_paths": ["../secret.txt"]},
        repo_root=repo_dir
    )
    assert len(context) == 0

@pytest.mark.asyncio
async def test_keyword_only_match_does_not_unlock_global_context(mock_ops_service, tmp_path):
    repo_dir = tmp_path / "repo_keyword"
    repo_dir.mkdir()
    (repo_dir / "other.py").write_text("secret")
    
    worker = RunWorker()
    context = worker._build_worker_context(
        task={"allowed_paths": ["non_existent.py"]},
        repo_root=repo_dir
    )
    assert len(context) == 0
    assert not any(f["path"] == "other.py" for f in context)
