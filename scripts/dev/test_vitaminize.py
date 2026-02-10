import os
from pathlib import Path

# Setup environment
os.environ["ORCH_TOKEN"] = "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"
os.environ["ORCH_REPO_ROOT"] = str(Path(__file__).parent.resolve())
os.environ["ORCH_HEADLESS"] = "true"

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token


# Mock token dependency
async def override_verify_token():
    return "test_actor"


app.dependency_overrides[verify_token] = override_verify_token

# Create test client
client = TestClient(app)

# Test 1: vitaminize with invalid path (should return 400)
print("Test 1: Vitaminize invalid path")
response = client.post("/ui/repos/vitaminize?path=C:/outside")
print(f"  Status code: {response.status_code}")
print("  Expected: 400")
print(f"  Pass: {response.status_code == 400}")

# Test 2: Check if route exists
print("\nTest 2: Check route exists")
response = client.post("/ui/repos/vitaminize?path=/fake/path")
print(f"  Status code: {response.status_code}")
print(f"  Not 404: {response.status_code != 404}")
