"""Shared pytest configuration and fixtures for all test modules."""
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

# Set environment variables for testing BEFORE importing the app
os.environ.setdefault("ORCH_TOKEN", "test-token-1234567890-very-secure")
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.repo_orchestrator.main import app


@pytest.fixture(scope="session")
def test_client():
    """Provide a TestClient with properly initialized lifespan context."""
    client = TestClient(app, raise_server_exceptions=False)
    with client:
        yield client


@pytest.fixture(scope="function", autouse=True)
def reset_test_state():
    """Reset any global state between tests."""
    from tools.repo_orchestrator.security import rate_limit_store
    rate_limit_store.clear()
    yield
