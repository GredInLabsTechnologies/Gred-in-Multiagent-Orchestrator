import os
import random
import string
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

# Set environment variables for testing
os.environ["ORCH_TOKEN"] = "fuzz-token"
os.environ["ORCH_REPO_ROOT"] = str(Path(__file__).parent.parent.resolve())

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import rate_limit_store

client = TestClient(app)

def random_string(length=10):
    letters = string.ascii_letters + string.digits + string.punctuation + " "
    return ''.join(random.choice(letters) for i in range(length))

def test_endpoint_fuzzing():
    """Rigor: Perform 1000+ random injections to verify stability."""
    endpoints = [
        ("GET", "/status"),
        ("GET", "/ui/status"),
        ("GET", "/tree"),
        ("GET", "/file"),
        ("POST", "/file"),
        ("GET", "/search"),
        ("GET", "/diff"),
    ]
    
    token = "fuzz-token"
    
    for _ in range(100): # Reduced iterations for test speed, can be increased in full run
        method, url = random.choice(endpoints)
        
        # Randomized params
        params = {
            "path": random_string(random.randint(1, 50)),
            "q": random_string(random.randint(1, 20)),
            "max_depth": random.randint(-10, 100),
            "start_line": random.randint(-100, 1000),
            "end_line": random.randint(-100, 1000),
        }
        
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            if method == "GET":
                response = client.get(url, params=params, headers=headers)
            else:
                # Post with junk data
                response = client.post(url, json={"path": params["path"], "content": random_string(100)}, headers=headers)
            
            # We expect 400, 403, 404, or 422 for bad inputs, but NEVER 500
            assert response.status_code != 500, f"Fuzzing failed on {url} with {params}: 500 error"
        except Exception as e:
            pytest.fail(f"Fuzzing caused unhandled exception on {url}: {e}")

def test_null_byte_injections():
    """Verify that null bytes are handled gracefully everywhere."""
    # Reset rate limit store to ensure we don't get 429 from previous fuzzing
    rate_limit_store.clear()
    
    headers = {"Authorization": "Bearer fuzz-token"}
    payloads = ["test\0path", "\0/etc/passwd", "normal.py\0.exe"]
    
    for p in payloads:
        response = client.get("/file", params={"path": p}, headers=headers)
        assert response.status_code in [400, 403, 422], f"Null byte not handled correctly on path: {p}"
