"""P0 real validation tests using Ollama + qwen2.5-coder:3b.

These tests verify that GIMO can actually:
1. Call a real LLM via ProviderService.static_generate()
2. Receive coherent generated code
3. Write that code to disk correctly

All tests require a running Ollama instance with qwen2.5-coder:3b loaded.
Run with: pytest -m ollama --timeout=120 -v
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.ollama, pytest.mark.integration]

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_V1_URL = f"{OLLAMA_BASE_URL}/v1"
OLLAMA_MODEL = "qwen2.5-coder:3b"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ollama_available():
    """Skip entire module if Ollama is not running or model not available."""
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        # Accept both exact and tag-suffixed names (e.g. "qwen2.5-coder:3b")
        if not any(OLLAMA_MODEL in m for m in models):
            pytest.skip(f"Model {OLLAMA_MODEL} not found in Ollama (available: {models})")
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        pytest.skip("Ollama not running — skipping real LLM tests")


@pytest.fixture()
def ollama_provider_config(tmp_path: Path):
    """Patch ProviderService.CONFIG_FILE to a temp provider.json with Ollama."""
    config = {
        "schema_version": 2,
        "active": "ollama-local",
        "providers": {
            "ollama-local": {
                "type": "custom_openai_compatible",
                "base_url": OLLAMA_V1_URL,
                "api_key": "",
                "model": OLLAMA_MODEL,
            }
        },
    }
    config_file = tmp_path / "provider.json"
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    from tools.gimo_server.services.providers.service_impl import ProviderService

    original = ProviderService.CONFIG_FILE
    ProviderService.CONFIG_FILE = config_file
    # Clear any cached LLM cache to avoid stale hits
    ProviderService._cache_instance = None
    yield config_file
    ProviderService.CONFIG_FILE = original
    ProviderService._cache_instance = None


@pytest.fixture()
def real_workspace(tmp_path: Path):
    """Provide a clean temp directory as workspace for file operations."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Test 1: Direct LLM call
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_ollama_generates_code(ollama_available, ollama_provider_config):
    """ProviderService.static_generate() returns real code from Ollama."""
    from tools.gimo_server.services.providers.service_impl import ProviderService

    prompt = (
        "Write a Python function called 'add' that takes two numbers a and b "
        "and returns their sum. Output ONLY the function code, no explanation."
    )
    result = asyncio.run(
        ProviderService.static_generate(prompt, {"task_type": "code"})
    )

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "content" in result, f"Missing 'content' key: {result.keys()}"

    content = result["content"]
    assert "def add" in content, f"Expected 'def add' in response:\n{content}"
    assert "return" in content, f"Expected 'return' in response:\n{content}"
    assert result.get("provider") == "ollama-local"
    assert result.get("model") == OLLAMA_MODEL
    assert result.get("tokens_used", 0) > 0


# ---------------------------------------------------------------------------
# Test 2: Full file_task pipeline
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_file_task_pipeline_writes_real_code(
    ollama_available, ollama_provider_config, real_workspace
):
    """Full pipeline: LLM generates code → file is written to disk."""
    from tools.gimo_server.engine.tools.executor import ToolExecutor
    from tools.gimo_server.services.providers.service_impl import ProviderService

    prompt = (
        "Write a short Python script that prints 'Hello, GIMO!'. "
        "Output ONLY the Python code, no explanation or markdown."
    )

    # Step 1: Real LLM call
    result = asyncio.run(
        ProviderService.static_generate(prompt, {"task_type": "code"})
    )
    generated_code = result["content"]

    # Strip markdown fences if the model wraps them
    code = _strip_markdown_fences(generated_code)

    # Step 2: Write to disk via ToolExecutor
    executor = ToolExecutor(workspace_root=str(real_workspace))
    write_result = asyncio.run(
        executor.execute_tool_call("write_file", {
            "path": "hello.py",
            "content": code,
        })
    )
    assert write_result["status"] == "success", f"File write failed: {write_result}"

    # Step 3: Verify file on disk
    written_file = real_workspace / "hello.py"
    assert written_file.exists(), "hello.py was not created"
    file_content = written_file.read_text(encoding="utf-8")
    assert len(file_content) > 0, "File is empty"

    # Step 4: Verify it's valid Python
    try:
        compile(file_content, "hello.py", "exec")
    except SyntaxError as e:
        pytest.fail(f"Generated code has syntax errors:\n{file_content}\n\nError: {e}")


# ---------------------------------------------------------------------------
# Test 3: Syntactic validity of generated code
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_generated_code_is_syntactically_valid(ollama_available, ollama_provider_config):
    """LLM-generated class code parses with ast.parse()."""
    from tools.gimo_server.services.providers.service_impl import ProviderService

    prompt = (
        "Write a Python class called Calculator with methods: add, subtract, multiply, divide. "
        "Each method takes two parameters (a, b) and returns the result. "
        "Handle division by zero in the divide method. "
        "Output ONLY the class code, no explanation or markdown."
    )

    result = asyncio.run(
        ProviderService.static_generate(prompt, {"task_type": "code"})
    )
    content = result["content"]
    code = _strip_markdown_fences(content)

    # Must parse without errors
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        pytest.fail(f"Generated code failed ast.parse():\n{code}\n\nError: {e}")

    # Must contain the class
    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    assert "Calculator" in class_names, (
        f"Expected class 'Calculator', found: {class_names}\n\nCode:\n{code}"
    )

    # Must contain the expected methods
    methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            methods.add(node.name)
    expected = {"add", "subtract", "multiply", "divide"}
    missing = expected - methods
    assert not missing, f"Missing methods: {missing}. Found: {methods}\n\nCode:\n{code}"


# ---------------------------------------------------------------------------
# Test 4: Risk gate still blocks high-risk requests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_pipeline_respects_risk_gate(
    ollama_available, ollama_provider_config, real_workspace
):
    """RiskGate rejects high-risk requests even with a real LLM backend."""
    from tools.gimo_server.engine.contracts import StageInput, StageOutput
    from tools.gimo_server.engine.stages.risk_gate import RiskGate

    stage = RiskGate()
    inp = StageInput(
        run_id="test-risk-001",
        context={},
        artifacts={
            "intent_audit": {
                "intent_effective": "SECURITY_CHANGE",
                "risk_score": 100,
            }
        },
    )

    output: StageOutput = asyncio.run(
        stage.execute(inp)
    )

    # RiskGate should halt or fail on score >= threshold (review_max)
    assert output.status in ("halt", "fail"), (
        f"Expected risk gate to reject (halt/fail), got: {output.status}\n"
        f"Artifacts: {output.artifacts}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_markdown_fences(text: str) -> str:
    """Remove ```python ... ``` wrappers from LLM output."""
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
