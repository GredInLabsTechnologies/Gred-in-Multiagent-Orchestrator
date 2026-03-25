import pytest
from unittest.mock import MagicMock
from cli_commands import dispatch_slash_command, COMMAND_REGISTRY


@pytest.fixture
def mock_callbacks():
    """Returns a dictionary of mock callbacks for testing slash commands."""
    return {
        "show_help": MagicMock(return_value=None),
        "show_workspace": MagicMock(return_value=None),
        "show_thread": MagicMock(return_value=None),
        "exit_session": MagicMock(return_value=None),
        "handle_provider": MagicMock(return_value=None),
        "handle_model": MagicMock(return_value=None),
        "list_models": MagicMock(return_value=None),
        "show_workers": MagicMock(return_value=None),
        "show_status": MagicMock(return_value=None),
        "undo": MagicMock(return_value=None),
        "clear_view": MagicMock(return_value=None),
        "reset_context": MagicMock(return_value=None),
        "show_tokens": MagicMock(return_value=None),
        "show_diff": MagicMock(return_value=None),
        "set_effort": MagicMock(return_value=None),
        "set_permissions": MagicMock(return_value=None),
        "add_file": MagicMock(return_value=None),
        "invalid_arg": MagicMock(return_value=None),
        "unknown_command": MagicMock(return_value=None),
    }


def test_registry_contains_all_p0_commands():
    """Verify that all 8 new P0 commands are registered."""
    expected_commands = {
        "/undo", "/clear", "/reset", "/tokens", "/diff", 
        "/effort", "/permissions", "/add"
    }
    registered = {cmd.name for cmd in COMMAND_REGISTRY}
    assert expected_commands.issubset(registered), f"Missing commands: {expected_commands - registered}"


@pytest.mark.parametrize("command_str, callback_name, arg_called_with", [
    ("/undo", "undo", None),
    ("/clear", "clear_view", None),
    ("/reset", "reset_context", None),
    ("/tokens", "show_tokens", None),
    ("/diff", "show_diff", None),
])
def test_simple_p0_commands(mock_callbacks, command_str, callback_name, arg_called_with):
    """Test commands that do not take arguments."""
    handled, new_model = dispatch_slash_command(command_str, "", mock_callbacks)
    
    assert handled is True
    assert new_model is None
    
    # Assert the specific callback was called
    cb = mock_callbacks[callback_name]
    cb.assert_called_once()
    if arg_called_with is not None:
        cb.assert_called_with(arg_called_with)


def test_effort_command_valid(mock_callbacks):
    """Test /effort with a valid argument."""
    handled, new_model = dispatch_slash_command("/effort", "max", mock_callbacks)
    assert handled is True
    mock_callbacks["set_effort"].assert_called_once_with("max")
    mock_callbacks["invalid_arg"].assert_not_called()


def test_effort_command_invalid(mock_callbacks):
    """Test /effort with an invalid argument."""
    handled, new_model = dispatch_slash_command("/effort", "supermax", mock_callbacks)
    assert handled is True
    mock_callbacks["set_effort"].assert_not_called()
    mock_callbacks["invalid_arg"].assert_called_once()


def test_permissions_command_valid(mock_callbacks):
    """Test /permissions with a valid sequence of arguments."""
    handled, new_model = dispatch_slash_command("/permissions", "suggest", mock_callbacks)
    assert handled is True
    mock_callbacks["set_permissions"].assert_called_with("suggest")
    
    handled, new_model = dispatch_slash_command("/permissions", "auto-edit", mock_callbacks)
    assert handled is True
    mock_callbacks["set_permissions"].assert_called_with("auto-edit")


def test_permissions_command_invalid(mock_callbacks):
    """Test /permissions with an invalid argument."""
    handled, new_model = dispatch_slash_command("/permissions", "root", mock_callbacks)
    assert handled is True
    mock_callbacks["set_permissions"].assert_not_called()
    mock_callbacks["invalid_arg"].assert_called_once()


def test_add_command_valid(mock_callbacks):
    """Test /add with a provided argument."""
    handled, new_model = dispatch_slash_command("/add", "src/main.py", mock_callbacks)
    assert handled is True
    mock_callbacks["add_file"].assert_called_once_with("src/main.py")


def test_add_command_empty(mock_callbacks):
    """Test /add with no arguments."""
    handled, new_model = dispatch_slash_command("/add", "", mock_callbacks)
    assert handled is True
    mock_callbacks["add_file"].assert_not_called()
    mock_callbacks["invalid_arg"].assert_called_once()


def test_unknown_slash_command(mock_callbacks):
    """Test behavior when an unknown slash command is dispatched."""
    handled, new_model = dispatch_slash_command("/fakecmd", "", mock_callbacks)
    assert handled is True
    mock_callbacks["unknown_command"].assert_called_once_with("/fakecmd")
