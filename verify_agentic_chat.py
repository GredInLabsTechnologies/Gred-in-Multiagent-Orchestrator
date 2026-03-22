#!/usr/bin/env python3
"""Verification script for GIMO Agentic Chat implementation.

Checks:
1. All critical imports work
2. Tool schemas and handlers are complete
3. LLM adapter has chat_with_tools
4. Agentic loop service is functional
5. Endpoint is registered
6. CLI imports work
7. All tests pass
"""
from __future__ import annotations

import sys


def verify_imports():
    """Verify all critical imports."""
    print("[OK] Verifying imports...")

    try:
        from tools.gimo_server.engine.tools.chat_tools_schema import CHAT_TOOLS, get_tool_risk_level
        assert len(CHAT_TOOLS) == 8, f"Expected 8 tools, got {len(CHAT_TOOLS)}"
        print(f"  [OK] chat_tools_schema: {len(CHAT_TOOLS)} tools")
    except Exception as e:
        print(f"  [FAIL] chat_tools_schema: {e}")
        return False

    try:
        from tools.gimo_server.services.agentic_loop_service import AgenticLoopService, AgenticResult
        result = AgenticResult("test")
        assert hasattr(result, "finish_reason"), "AgenticResult missing finish_reason"
        assert result.finish_reason == "stop", f"Expected default 'stop', got {result.finish_reason}"
        print(f"  [OK] agentic_loop_service: AgenticResult has finish_reason={result.finish_reason}")
    except Exception as e:
        print(f"  [FAIL] agentic_loop_service: {e}")
        return False

    try:
        from gimo_cli_renderer import ChatRenderer
        print("  [OK] gimo_cli_renderer imported")
    except Exception as e:
        print(f"  [FAIL] gimo_cli_renderer: {e}")
        return False

    try:
        from tools.gimo_server.providers.openai_compat import OpenAICompatAdapter
        assert hasattr(OpenAICompatAdapter, "chat_with_tools"), "OpenAICompatAdapter missing chat_with_tools"
        print("  [OK] OpenAICompatAdapter has chat_with_tools")
    except Exception as e:
        print(f"  [FAIL] OpenAICompatAdapter: {e}")
        return False

    return True


def verify_tool_executor():
    """Verify ToolExecutor has all handlers."""
    print("\n[OK] Verifying ToolExecutor...")

    try:
        from tools.gimo_server.engine.tools.executor import ToolExecutor

        required_handlers = [
            "handle_read_file",
            "handle_write_file",
            "handle_list_files",
            "handle_search_text",
            "handle_search_replace",
            "handle_shell_exec",
            "handle_patch_file",
            "handle_create_dir",
        ]

        missing = []
        for handler in required_handlers:
            if not hasattr(ToolExecutor, handler):
                missing.append(handler)

        if missing:
            print(f"  [FAIL] Missing handlers: {missing}")
            return False

        print(f"  [OK] All {len(required_handlers)} handlers present")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def verify_endpoint():
    """Verify chat endpoint is registered."""
    print("\n[OK] Verifying endpoint...")

    try:
        from tools.gimo_server.routers.ops.conversation_router import router

        routes = [r.path for r in router.routes]
        if "/threads/{thread_id}/chat" not in routes:
            print(f"  [FAIL] /threads/{{thread_id}}/chat not in routes: {routes}")
            return False

        # Check for duplicates
        chat_routes = [r for r in routes if r == "/threads/{thread_id}/chat"]
        if len(chat_routes) > 1:
            print(f"  [FAIL] Duplicate /chat endpoint found ({len(chat_routes)} times)")
            return False

        print("  [OK] POST /ops/threads/{thread_id}/chat registered (no duplicates)")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def verify_agentic_loop():
    """Verify AgenticLoopService.run() signature."""
    print("\n[OK] Verifying AgenticLoopService...")

    try:
        import inspect
        from tools.gimo_server.services.agentic_loop_service import AgenticLoopService

        sig = inspect.signature(AgenticLoopService.run)
        params = list(sig.parameters.keys())

        expected = ["thread_id", "user_message", "workspace_root", "token"]
        if params != expected:
            print(f"  [FAIL] run() params: expected {expected}, got {params}")
            return False

        print(f"  [OK] run() signature: {params}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def verify_tests():
    """Verify tests pass."""
    print("\n[OK] Verifying tests...")

    import subprocess

    try:
        result = subprocess.run(
            ["python", "-m", "pytest",
             "tests/unit/test_chat_tools.py",
             "tests/unit/test_agentic_loop.py",
             "-v", "--tb=line"],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print(f"  [FAIL] Tests failed:\n{result.stdout[-500:]}")
            return False

        # Count passed tests
        import re
        passed = re.search(r"(\d+) passed", result.stdout)
        if passed:
            print(f"  [OK] {passed.group(1)} tests passed")
        else:
            print("  [OK] Tests passed")

        return True
    except subprocess.TimeoutExpired:
        print("  [FAIL] Tests timed out")
        return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def main():
    """Run all verifications."""
    print("=" * 60)
    print("GIMO Agentic Chat — Verificación de Implementación")
    print("=" * 60)

    checks = [
        ("Imports", verify_imports),
        ("ToolExecutor", verify_tool_executor),
        ("Endpoint", verify_endpoint),
        ("AgenticLoop", verify_agentic_loop),
        ("Tests", verify_tests),
    ]

    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"\n[FAIL] {name} check crashed: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("RESUMEN:")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "[OK] PASS" if passed else "[FAIL] FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("[OK] TODAS LAS VERIFICACIONES PASARON")
        print("[OK] Implementación lista para producción")
        return 0
    else:
        print("[FAIL] ALGUNAS VERIFICACIONES FALLARON")
        print("[FAIL] Revisar errores arriba")
        return 1


if __name__ == "__main__":
    sys.exit(main())
