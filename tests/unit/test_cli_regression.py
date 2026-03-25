import json
from unittest.mock import patch

from gimo import _handle_chat_slash_command, _terminal_status
from gimo_cli_renderer import ChatRenderer


def test_terminal_status():
    # Test existing known states
    assert _terminal_status("done") is True
    assert _terminal_status("error") is True
    assert _terminal_status("cancelled") is True
    # Test non-terminal
    assert _terminal_status("running") is False
    assert _terminal_status("pending") is False
    assert _terminal_status("awaiting_subagents") is False
    # Test completely unknown generic
    assert _terminal_status("some_unknown_weird_state") is False


def test_handle_chat_slash_command_workspace():
    # Test the simplest command that has no remote dependency
    config = {}
    handled, res = _handle_chat_slash_command(
        config, "/workspace", workspace_root="/fake/root", thread_id="t123"
    )
    assert handled is True
    assert res is None


def test_handle_chat_slash_command_thread():
    config = {}
    handled, res = _handle_chat_slash_command(
        config, "/thread", workspace_root="/fake/root", thread_id="t123"
    )
    assert handled is True
    assert res is None


@patch("gimo.console.print")
def test_handle_chat_slash_command_help(mock_print):
    config = {}
    handled, res = _handle_chat_slash_command(
        config, "/help", workspace_root="/fake/root", thread_id="t123"
    )
    assert handled is True
    assert res is None
    # Verify print was called (so help text was rendered)
    mock_print.assert_called()


def test_chat_renderer_plan_approval_yes():
    renderer = ChatRenderer()
    # Mocking input
    with patch.object(renderer.console, "input", return_value="y"):
        assert renderer.get_plan_approval() == "approve"
    with patch.object(renderer.console, "input", return_value="yes"):
        assert renderer.get_plan_approval() == "approve"
    with patch.object(renderer.console, "input", return_value="si"):
        assert renderer.get_plan_approval() == "approve"
    with patch.object(renderer.console, "input", return_value="sí"):
        assert renderer.get_plan_approval() == "approve"


def test_chat_renderer_plan_approval_no():
    renderer = ChatRenderer()
    with patch.object(renderer.console, "input", return_value="n"):
        assert renderer.get_plan_approval() == "reject"
    with patch.object(renderer.console, "input", return_value="no"):
        assert renderer.get_plan_approval() == "reject"
    with patch.object(renderer.console, "input", return_value="random_junk"):
        assert renderer.get_plan_approval() == "reject"


def test_chat_renderer_plan_approval_modify():
    renderer = ChatRenderer()
    with patch.object(renderer.console, "input", return_value="m"):
        assert renderer.get_plan_approval() == "modify"
    with patch.object(renderer.console, "input", return_value="modify"):
        assert renderer.get_plan_approval() == "modify"


@patch("gimo_cli_renderer.Console.print")
def test_chat_renderer_tool_call_write_file(mock_print):
    renderer = ChatRenderer()
    tool = {
        "name": "write_file",
        "status": "success",
        "duration": 1.2,
        "arguments": {"path": "test.txt", "content": "hello world"}
    }
    renderer.render_tool_call(tool)
    # Check that print was called with old/new text (for write_file it prints path and content len)
    # It prints multiple times: the tool summary then the content summary
    assert mock_print.call_count == 2
    args = mock_print.call_args_list[1][0]
    assert "test.txt" in args[0]
    assert "11 chars" in args[0]


@patch("gimo_cli_renderer.Console.print")
def test_chat_renderer_tool_call_search_replace(mock_print):
    renderer = ChatRenderer()
    tool = {
        "name": "search_replace",
        "status": "success",
        "duration": 0.5,
        "arguments": {"old_text": "foo", "new_text": "bar"}
    }
    renderer.render_tool_call(tool)
    # It prints 3 times: summary, old text, new text
    assert mock_print.call_count == 3
    assert "old: foo" in mock_print.call_args_list[1][0][0]
    assert "new: bar" in mock_print.call_args_list[2][0][0]


from unittest.mock import MagicMock
from gimo import _project_root
import subprocess
from pathlib import Path

def test_project_root_git_repo(monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value.stdout = 'C:/fake/repo\n'
    monkeypatch.setattr(subprocess, 'run', mock_run)
    
    root = _project_root()
    assert str(root).replace('\\', '/') == 'C:/fake/repo'

def test_project_root_no_git(monkeypatch):
    def mock_run_fail(*args, **kwargs):
        raise Exception('Not a git repo')
    monkeypatch.setattr(subprocess, 'run', mock_run_fail)
    
    root = _project_root()
    assert root == Path.cwd()

@patch('gimo._write_json')
@patch('gimo._runs_dir', return_value=Path('/fake/runs'))
def test_run_artifact_persistence(mock_runs_dir, mock_write_json):
    from gimo import app
    from typer.testing import CliRunner
    runner = CliRunner()
    
    with patch('gimo._load_config', return_value={}): 
        with patch('gimo._api_request', return_value=(200, {'run': {'id': 'run-999'}}, )):
            result = runner.invoke(app, ['run', 'plan-123', '--no-confirm', '--no-wait'])
            
            # Should have written to run-999.json
            args, kwargs = mock_write_json.call_args
            assert 'run-999.json' in str(args[0])
            
        with patch('gimo._api_request', return_value=(200, {'run': None}, )):
            result = runner.invoke(app, ['run', 'plan-123', '--no-confirm', '--no-wait'])
            
            # Should have written to plan-123_RANDOM.json
            args, kwargs = mock_write_json.call_args
            assert 'plan-123_' in str(args[0])
            assert 'run-999.json' not in str(args[0])

def test_handle_chat_slash_command_permissions(monkeypatch):
    import gimo
    config = {}
    
    captured = {}
    def _fake_api_request(cfg, method, path, *, params=None, json_body=None):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        return 200, {"ok": True}
        
    monkeypatch.setattr(gimo, "_api_request", _fake_api_request)
    
    handled, res = gimo._handle_chat_slash_command(
        config, "/permissions auto-edit", workspace_root="/fake/root", thread_id="t123"
    )
    assert handled is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/ops/threads/t123/config"
    assert captured["json_body"] == {"permissions": "auto-edit"}

def test_tui_update_topology_uses_operator_status(monkeypatch):
    from gimo_tui import GimoApp
    app = GimoApp()
    
    captured_paths = []
    
    def _fake_api_request(cfg, method, path, *, params=None, json_body=None):
        captured_paths.append(path)
        if path == "/ops/operator/status":
            return 200, {
                "repo": "some_repo",
                "branch": "main",
                "active_provider": "openai",
                "active_model": "gpt-4o"
            }
        return 404, {}

    monkeypatch.setattr("gimo_tui._api_request", _fake_api_request)
    
    app._update_graph_widget = MagicMock()
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)
    app._refresh_topology_logic()
    
    assert "/ops/operator/status" in captured_paths
    assert "/ops/provider" not in captured_paths
    app._update_graph_widget.assert_called()
    call_arg = app._update_graph_widget.call_args[0][0]
    assert "some_repo" in str(call_arg)
    assert "openai" in str(call_arg)

