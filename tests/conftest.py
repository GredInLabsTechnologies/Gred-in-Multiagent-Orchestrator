"""Shared pytest configuration and fixtures for all test modules."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

IGNORED_COLLECTION_FILES = {"test_diag_2.txt", "test_failures.txt"}

# Set environment variables for testing BEFORE importing the app
# Default token - will be reset by clean_environment fixture
DEFAULT_TEST_TOKEN = os.environ.get("ORCH_TEST_TOKEN") or os.environ.get(
    "ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"
)
DEFAULT_TEST_ACTOR = os.environ.get("ORCH_TEST_ACTOR", "test_actor")
os.environ.setdefault("ORCH_TOKEN", DEFAULT_TEST_TOKEN)
os.environ.setdefault("ORCH_TEST_ACTOR", DEFAULT_TEST_ACTOR)
os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.gimo_server.main import app  # noqa: E402


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Ignore non-test diagnostic artifacts stored in the repo root."""
    if collection_path.name in IGNORED_COLLECTION_FILES:
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
    )

    rate_limit_store.clear()

    # Reset panic mode AND recent_events in DB to prevent state leakage
    try:
        db = load_security_db()
        if db.get("panic_mode") or db.get("recent_events"):
            db["panic_mode"] = False
            db["recent_events"] = []
            save_security_db(db)
    except Exception as exc:
        import logging

        logging.getLogger("orchestrator.tests").warning("Failed to reset security state: %s", exc)

    yield
