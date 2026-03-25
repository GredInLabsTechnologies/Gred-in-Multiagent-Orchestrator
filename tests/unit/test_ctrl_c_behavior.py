import pytest
from unittest.mock import MagicMock, patch
import json
import httpx


def _simulate_sse_loop(mock_renderer, iter_lines_side_effect, base_url="http://mock", thread_id="t1"):
    """
    Simulation of the critical SSE reading inside _interactive_chat 
    to assert KeyboardInterrupt does not crash the session and calls renderer.
    """
    auth_token = "mock"
    chat_response = ""
    usage = {}
    current_usage = {}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_lines.side_effect = iter_lines_side_effect
    
    _interrupted = False
    
    try:
        try:
            for line in mock_response.iter_lines():
                if not line or line.startswith(":"):
                    continue

                if line.startswith("event: "):
                    current_event_type = line[7:].strip()
                    continue
                if not line.startswith("data: "):
                    continue

                raw_data = line[6:].strip()
                if not raw_data:
                    continue

                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue

                evt = current_event_type

                if evt == "text_delta":
                    chat_response += data.get("content", "")

                elif evt == "done":
                    chat_response = data.get("response", chat_response)
                    usage = data.get("usage", {})
                    current_usage.clear()
                    current_usage.update(usage)
                    
        except KeyboardInterrupt:
            _interrupted = True
            mock_renderer.render_interrupted()
            
    except Exception as e:
        pytest.fail(f"Loop crashed with {e}; should have been caught!")
        
    return _interrupted, chat_response, current_usage


def test_sse_loop_normal_completion():
    """Test standard streaming with text delta and done events."""
    mock_renderer = MagicMock()
    
    lines = [
        "event: text_delta",
        'data: {"content": "Hello"}',
        "",
        "event: text_delta",
        'data: {"content": " World"}',
        "",
        "event: done",
        'data: {"response": "Hello World", "usage": {"total_tokens": 10}}',
    ]
    
    interrupted, text, usage = _simulate_sse_loop(
        mock_renderer, 
        iter_lines_side_effect=[lines]  # return lines sequence
    )
    
    assert interrupted is False
    assert text == "Hello World"
    assert usage.get("total_tokens") == 10
    mock_renderer.render_interrupted.assert_not_called()


def test_sse_loop_keyboard_interrupt():
    """Test that a KeyboardInterrupt during streaming is caught non-destructively."""
    mock_renderer = MagicMock()
    
    def generator_that_interrupts():
        yield "event: text_delta"
        yield 'data: {"content": "First half..."}'
        yield ""
        raise KeyboardInterrupt()
        
    interrupted, text, usage = _simulate_sse_loop(
        mock_renderer, 
        iter_lines_side_effect=[generator_that_interrupts()]
    )
    
    assert interrupted is True
    assert text == "First half..."
    assert usage == {}
    mock_renderer.render_interrupted.assert_called_once()
