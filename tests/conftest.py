"""Shared pytest configuration and fixtures for all test modules."""
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

# Set environment variables for testing BEFORE importing the app
# Default token - will be reset by clean_environment fixture
os.environ.setdefault("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.repo_orchestrator.main import app


@pytest.fixture(scope="session")
def test_client():
    """Provide a TestClient with properly initialized lifespan context."""
    client = TestClient(app, raise_server_exceptions=False)
    with client:
        yield client


@pytest.fixture(autouse=True)
def clean_environment():
    """Clean critical environment variables before each test."""
    # Backup current values
    old_token = os.environ.get('ORCH_TOKEN')
    
    # Reset to clean state - ensure valid token for most tests
    os.environ['ORCH_TOKEN'] = 'test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0'
    
    yield  # Test runs here
    
    # Restore original values
    if old_token:
        os.environ['ORCH_TOKEN'] = old_token
    else:
        os.environ.pop('ORCH_TOKEN', None)


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """Clear FastAPI dependency overrides after each test."""
    yield
    # Cleanup after test
    app.dependency_overrides.clear()


@pytest.fixture(scope="function", autouse=True)
def reset_test_state():
    """Reset any global state between tests."""
    from tools.repo_orchestrator.security import rate_limit_store
    rate_limit_store.clear()
    yield
