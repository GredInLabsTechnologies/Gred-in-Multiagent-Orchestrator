from tools.llm_security.prompts import HARDENED_SYSTEM_PROMPT, build_user_prompt


def test_hardened_system_prompt_exists():
    assert isinstance(HARDENED_SYSTEM_PROMPT, str)
    assert len(HARDENED_SYSTEM_PROMPT) > 500
    assert "STRICT SECURITY CONSTRAINTS" in HARDENED_SYSTEM_PROMPT
    assert "NEVER output API keys" in HARDENED_SYSTEM_PROMPT


def test_build_user_prompt_format():
    code = "def hello(): pass"
    prompt = build_user_prompt(code, "security")
    assert code in prompt
    assert "security" in prompt
    assert "ANALYSIS REQUEST" in prompt
    assert "CODE TO ANALYZE" in prompt
