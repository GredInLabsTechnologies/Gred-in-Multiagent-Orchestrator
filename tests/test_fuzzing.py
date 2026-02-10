import os
import secrets
import string
from pathlib import Path

import pytest

# Set environment variables for testing
# Use shared token from conftest.py
os.environ["ORCH_REPO_ROOT"] = str(Path(__file__).parent.parent.resolve())

from tools.gimo_server.security import rate_limit_store


def random_string(length: int = 10) -> str:
    """Generate a cryptographically secure random string for fuzzing."""
    alphabet = string.ascii_letters + string.digits + string.punctuation + " "
    return "".join(secrets.choice(alphabet) for _ in range(length))


def test_endpoint_fuzzing(test_client):
    """Rigor: Perform 100+ random injections to verify stability."""
    endpoints = [
        ("GET", "/status"),
        ("GET", "/ui/status"),
        ("GET", "/tree"),
        ("GET", "/file"),
        ("POST", "/file"),
        ("GET", "/search"),
        ("GET", "/diff"),
    ]

    token = os.environ.get("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")

    for _ in range(100):
        method, url = secrets.choice(endpoints)

        # Randomized params using secure random
        params = {
            "path": random_string(secrets.randbelow(50) + 1),
            "q": random_string(secrets.randbelow(20) + 1),
            "max_depth": secrets.randbelow(110) - 10,
            "start_line": secrets.randbelow(1100) - 100,
            "end_line": secrets.randbelow(1100) - 100,
        }

        headers = {"Authorization": f"Bearer {token}"}

        try:
            if method == "GET":
                response = test_client.get(url, params=params, headers=headers)
            else:
                # Post with junk data
                response = test_client.post(
                    url,
                    json={"path": params["path"], "content": random_string(100)},
                    headers=headers,
                )

            # We expect 400, 403, 404, or 422 for bad inputs, but NEVER 500
            assert response.status_code != 500, f"Fuzzing failed on {url} with {params}: 500 error"
        except Exception as e:
            pytest.fail(f"Fuzzing caused unhandled exception on {url}: {e}")


def test_null_byte_injections(test_client):
    """Verify that null bytes are handled gracefully everywhere."""
    # Reset rate limit store to ensure we don't get 429 from previous fuzzing
    rate_limit_store.clear()

    token = os.environ.get("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")
    headers = {"Authorization": f"Bearer {token}"}
    payloads = ["test\0path", "\0/etc/passwd", "normal.py\0.exe"]

    for p in payloads:
        response = test_client.get("/file", params={"path": p}, headers=headers)
        assert response.status_code in [
            400,
            403,
            422,
        ], f"Null byte not handled correctly on path: {p}"
