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
    assert _terminal_status("some_unknown_weird_state") is True


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
