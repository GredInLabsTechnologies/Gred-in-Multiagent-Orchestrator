"""Shared pytest configuration and fixtures for all test modules."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

IGonRED_COLLECTION_FILES = {"test_diag_2.txt", "test_failures.txt"}

# Set environment variables for testing BEFORE importing the app
# Default token - will be reset by clean_environment fixture
DEFAULT_TEST_TOKEN = os.environ.get("ORCH_TEST_TOKEN") or os.environ.get(
    "ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"
)
DEFAULT_TEST_ACTOR = os.environ.get("ORCH_TEST_ACTOR", "test_actor")
os.environ.setdefault("ORCH_TOKEN", DEFAULT_TEST_TOKEN)
os.environ.setdefault("ORCH_TEST_ACTOR", DEFAULT_TEST_ACTOR)
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))
# Test-safe defaults BEFORE importing app/config singletons
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ORCH_LICENSE_ALLOW_DEBUG_BYPASS", "true")
os.environ.setdefault("ORCH_AUDIT_LOG_MAX_BYTES", str(50 * 1024 * 1024))

from tools.gimo_server.main import app  # noqa: E402


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Ignore non-test diagnostic artifacts stored in the repo root."""
    if collection_path.name in IGonRED_COLLECTION_FILES:
        return True
    return None


@pytest.fixture(scope="session")
def test_client():
    """Provide a TestClient with properly initialized lifespan context."""
    client = TestClient(app, raise_server_exceptions=False)
    try:
        with client:
            yield client
    except BaseException as exc:
        # Suppress CancelledError during teardown (Python 3.14 compatibility)
        import asyncio

        if isinstance(exc, asyncio.CancelledError):
            return
        raise


@pytest.fixture(scope="session")
def valid_token() -> str:
    """Provide the canonical test token from environment for authenticated requests."""
    return os.environ["ORCH_TOKEN"]


@pytest.fixture(scope="session")
def test_actor() -> str:
    """Provide the canonical test actor for auth override contexts."""
    return os.environ["ORCH_TEST_ACTOR"]


@pytest.fixture(autouse=True)
def clean_environment():
    """Clean critical environment variables before each test."""
    # Backup current values
    old_token = os.environ.get("ORCH_TOKEN")

    # Reset to clean state - ensure valid token for most tests
    os.environ["ORCH_TOKEN"] = DEFAULT_TEST_TOKEN

    yield  # Test runs here

    # Restore original values
    if old_token:
        os.environ["ORCH_TOKEN"] = old_token
    else:
        os.environ.pop("ORCH_TOKEN", None)


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """Clear FastAPI dependency overrides after each test."""
    yield
    # Cleanup after test
    app.dependency_overrides.clear()


@pytest.fixture(scope="function", autouse=True)
def reset_test_state():
    """Reset any global state between tests."""
    from tools.gimo_server.security import (
        load_security_db,
        rate_limit_store,
        save_security_db,
        threat_engine
    )

    rate_limit_store.clear()
    threat_engine.clear_all()

    # Reset panic mode AND recent_events in DB to prevent state leakage
    try:
        db = load_security_db()
        # threat_engine.clear_all() already covers the logical state, 
        # but we also ensure the DB reflects it.
        db["panic_mode"] = False
        db["recent_events"] = []
        db["threat_level"] = 0
        save_security_db(db)
    except Exception as exc:
        import logging

        logging.getLogger("orchestrator.tests").warning("Failed to reset security state: %s", exc)

    yield


@pytest.fixture(scope="session", autouse=True)
def init_forensic_state():
    """Forensic initialization of system state without mocks."""
    from tools.gimo_server import config
    from tools.gimo_server.ops_models import OpsConfig, ProviderConfig, ToolEntry, UserEconomyConfig
    from tools.gimo_server.services.tool_registry_service import ToolRegistryService
    from tools.gimo_server.services.provider_service import ProviderService
    import json
    import sys

    # 1. Ensure tokens are registered in global config
    test_tokens = {
        DEFAULT_TEST_TOKEN,
        "test-operator-token-777",
        "test-actions-token-888"
    }
    config.TOKENS.update(test_tokens)

    # 2. Initialize Ops Data Directory
    ops_dir = config.OPS_DATA_DIR
    ops_dir.mkdir(parents=True, exist_ok=True)

    # 3. Force-merge forensic tool into registry
    registry_file = ToolRegistryService.REGISTRY_PATH
    registry_data = {}
    if registry_file.exists():
        try:
            registry_data = json.loads(registry_file.read_text(encoding="utf-8"))
        except: pass
    
    test_tool = ToolEntry(
        name="t1", 
        description="Test Tool", 
        metadata={"mcp_server": "s1", "mcp_tool": "real_t1"},
        allowed_roles=["operator", "admin"]
    )
    registry_data["t1"] = test_tool.model_dump()
    registry_file.write_text(json.dumps(registry_data, indent=2), encoding="utf-8")

    # 4. Create real provider config with s1 server
    provider_file = ops_dir / "provider.json"
    mcp_script = os.path.normpath(os.path.abspath(os.path.join(Path(__file__).parent.resolve(), "test_mcp_server.py")))
    prov_cfg = ProviderConfig(
        active="openai",
        providers={"openai": {"type": "openai", "model": "gpt-4o"}},
        mcp_servers={"s1": {"command": "python", "args": [mcp_script], "enabled": True}}
    )
    if provider_file.exists():
        try:
            # Merge existing servers
            old_cfg = ProviderConfig.model_validate_json(provider_file.read_text(encoding="utf-8"))
            prov_cfg.providers.update(old_cfg.providers)
            prov_cfg.mcp_servers.update(old_cfg.mcp_servers)
        except: pass
    provider_file.write_text(prov_cfg.model_dump_json(indent=2), encoding="utf-8")

    # 5. Disable economy budgets for tests (including anthropic for CostService hardcoded checks)
    config_file = ops_dir / "config.json"
    from tools.gimo_server.ops_models import ProviderBudget
    economy = UserEconomyConfig(
        global_budget_usd=1000000.0,
        provider_budgets=[
            ProviderBudget(provider="openai", max_cost_usd=1000000.0),
            ProviderBudget(provider="anthropic", max_cost_usd=1000000.0),
            ProviderBudget(provider="local", max_cost_usd=1000000.0),
        ],
        cache_enabled=False
    )
    ops_cfg = OpsConfig(economy=economy)
    config_file.write_text(ops_cfg.model_dump_json(indent=2), encoding="utf-8")

    yield
