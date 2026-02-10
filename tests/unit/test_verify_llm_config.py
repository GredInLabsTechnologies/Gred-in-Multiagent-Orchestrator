from unittest.mock import MagicMock

import scripts.tools.verify_llm_config as verify_llm_config


def test_build_payload_uses_expected_constants():
    payload = verify_llm_config.build_payload("system", "user")

    assert payload["model"] == verify_llm_config.MODEL_NAME
    assert payload["temperature"] == verify_llm_config.TEMPERATURE
    assert payload["max_tokens"] == verify_llm_config.MAX_TOKENS
    assert payload["messages"][0]["content"] == "system"
    assert payload["messages"][1]["content"] == "user"


def test_log_speed_branches():
    messages = []

    verify_llm_config.log_speed(messages.append, 3.0)
    verify_llm_config.log_speed(messages.append, 7.0)
    verify_llm_config.log_speed(messages.append, 12.0)

    assert any("EXCELLENT" in msg for msg in messages)
    assert any("ACCEPTABLE" in msg for msg in messages)
    assert any("SLOW" in msg for msg in messages)


def test_handle_success_logs_structured_output():
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": '{"command":"xss"}'}}]}
    messages = []

    verify_llm_config.handle_success(messages.append, response, 1.0)

    assert any("Structured Output" in msg for msg in messages)
    assert any("Command Extracted" in msg for msg in messages)
    assert any("SPEED TEST" in msg for msg in messages)
