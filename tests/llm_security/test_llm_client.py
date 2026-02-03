import hashlib
from unittest.mock import MagicMock, patch

import pytest

from tools.llm_security.llm_client import DeterministicLLM


def test_deterministic_seed_generation():
    system_prompt = "System info"
    user_prompt = "User query"

    # Manually calculate expected seed
    input_string = (system_prompt + user_prompt).encode("utf-8")
    input_hash = hashlib.sha256(input_string).hexdigest()
    expected_seed = int(input_hash[:8], 16) % (2**31)

    with patch("tools.llm_security.llm_client.OpenAI") as mock_openai:
        mock_instance = mock_openai.return_value
        mock_completion = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_completion
        mock_completion.choices = [MagicMock(message=MagicMock(content="Mock response"))]
        mock_completion.usage = MagicMock()
        mock_completion.usage.model_dump.return_value = {"total_tokens": 10}
        mock_completion.system_fingerprint = "fp_123"

        llm = DeterministicLLM(api_key="fake-key")
        result = llm.call_with_max_determinism(system_prompt, user_prompt)

        assert result["seed"] == expected_seed
        assert result["response"] == "Mock response"


def test_api_call_with_mock():
    with patch("tools.llm_security.llm_client.OpenAI") as mock_openai:
        mock_instance = mock_openai.return_value
        mock_completion = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_completion
        mock_completion.choices = [MagicMock(message=MagicMock(content="High-quality analysis"))]
        mock_completion.usage.model_dump.return_value = {
            "prompt_tokens": 50,
            "completion_tokens": 100,
        }
        mock_completion.system_fingerprint = "fp_456"

        llm = DeterministicLLM(api_key="fake-key")
        result = llm.call_with_max_determinism("Sys", "User")

        assert result["response"] == "High-quality analysis"
        assert result["model"] == "gpt-4-turbo-preview"
        assert "usage" in result
        assert result["fingerprint"] == "fp_456"

        # Verify OpenAI was called with correct parameters
        mock_instance.chat.completions.create.assert_called_once()
        call_kwargs = mock_instance.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0
        assert call_kwargs["seed"] is not None


def test_error_handling():
    with patch("tools.llm_security.llm_client.OpenAI") as mock_openai:
        mock_instance = mock_openai.return_value
        mock_instance.chat.completions.create.side_effect = Exception("API Connection Error")

        llm = DeterministicLLM(api_key="fake-key")
        result = llm.call_with_max_determinism("Sys", "User")

        assert "error" in result
        assert result["action"] == "DENY"
        assert "API Connection Error" in result["error"]


def test_response_format():
    with patch("tools.llm_security.llm_client.OpenAI") as mock_openai:
        mock_instance = mock_openai.return_value
        mock_completion = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_completion
        mock_completion.choices = [MagicMock(message=MagicMock(content="Response"))]
        mock_completion.usage.model_dump.return_value = {}
        mock_completion.system_fingerprint = "fp"

        llm = DeterministicLLM(api_key="fake-key")
        result = llm.call_with_max_determinism("S", "U")

        expected_keys = {"response", "usage", "fingerprint", "seed", "model"}
        assert set(result.keys()) == expected_keys


def test_init_validation():
    with pytest.raises(ValueError):
        DeterministicLLM(api_key="")
