import os
from pathlib import Path

import requests

ORCH_URL = "http://127.0.0.1:9325"
TOKEN = os.environ.get("ORCH_TOKEN")
SNAPSHOT_DIR = Path(__file__).parent.parent.resolve() / ".orch_snapshots"


def verify():
    if not TOKEN:
        print("[FAIL] ORCH_TOKEN not found.")
        return

    headers = {"Authorization": f"Bearer {TOKEN}"}

    # 1. Test GET /file (Snapshot creation)
    print("[*] Testing GET /file (Snapshot creation)...")
    test_file = "tools/gimo_server/config.py"
    r_get = requests.get(
        f"{ORCH_URL}/file", headers=headers, params={"path": test_file}, timeout=10
    )
    print(f"    Status: {r_get.status_code}")
    if r_get.status_code == 200:
        print("    [PASS] File read successfully.")
        # Check if snapshot exist
        snapshots = list(SNAPSHOT_DIR.iterdir()) if SNAPSHOT_DIR.exists() else []
        if snapshots:
            print(f"    [PASS] Found {len(snapshots)} snapshots in {SNAPSHOT_DIR}")
        else:
            print("    [FAIL] No snapshots found after read.")
    else:
        print(f"    [FAIL] GET /file returned {r_get.status_code}")

    # 2. Test POST /file (Hard deletion)
    print("\n[*] Testing POST /file (Hard deletion)...")
    r_post = requests.post(
        f"{ORCH_URL}/file",
        headers=headers,
        json={"path": "test.txt", "content": "fail"},
        timeout=10,
    )
    print(f"    Status: {r_post.status_code}")
    if r_post.status_code == 404 or r_post.status_code == 405:
        print("    [PASS] POST /file is disabled (404/405).")
    else:
        print(f"    [FAIL] POST /file still accessible (Status: {r_post.status_code})")

    # 3. Test UI POST endpoints
    print("\n[*] Testing /ui/repos/select (Hard deletion)...")
    r_ui = requests.post(
        f"{ORCH_URL}/ui/repos/select", headers=headers, params={"path": "."}, timeout=10
    )
    print(f"    Status: {r_ui.status_code}")
    if r_ui.status_code == 404:
        print("    [PASS] UI POST endpoint is disabled.")
    else:
        print("    [FAIL] UI POST endpoint still accessible.")


if __name__ == "__main__":
    verify()
