import os
import json
import sys
from pathlib import Path

def check_json_file(path, required_keys=None):
    if not path.exists():
        print(f"[ERROR] Missing file: {path}")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if required_keys:
                for key in required_keys:
                    if key not in data:
                        print(f"[ERROR] Missing key '{key}' in {path}")
            return data
    except Exception as e:
        print(f"[ERROR] Failed to parse {path}: {e}")
        return None

def main():
    print("--- Gred-Repo-Orchestrator Integrity Check ---")
    base_dir = Path(__file__).parent.parent.resolve()
    print(f"Base Directory: {base_dir}")

    # 1. Config Files
    print("\n1. Validating JSON Configuration Files:")
    repo_registry = check_json_file(base_dir / "tools" / "repo_orchestrator" / "repo_registry.json", ["repos", "active_repo"])
    check_json_file(base_dir / "tools" / "repo_orchestrator" / "allowed_paths.json", ["paths"])
    check_json_file(base_dir / "tools" / "repo_orchestrator" / "security_db.json", ["panic_mode", "blacklist", "recent_events"])

    # 2. Repo Existence
    if repo_registry:
        print("\n2. Verifying Repository Paths:")
        for repo_path in repo_registry.get("repos", []):
            if os.path.exists(repo_path):
                print(f"[OK] {repo_path}")
            else:
                print(f"[WARNING] Missing Repository: {repo_path}")

    # 3. Environment (Semi-check, as we don't have .env here but can check .env.example)
    print("\n3. Environment Variables (Required in OS or .env):")
    required_envs = ["ORCH_TOKEN", "ORCH_REPO_ROOT"]
    for env in required_envs:
        if os.environ.get(env):
            print(f"[OK] {env} is set")
        else:
            print(f"[INFO] {env} is not set in current shell (check your .env)")

    # 4. Migration Check: Searching for broken references
    print("\n4. Migration Check (Searching for missing file references):")
    hardcoded_found = False
    # Search for all .py, .ts, .tsx files and look for imports that might reference external things
    for root, dirs, files in os.walk(base_dir):
        if any(d in root for d in ["node_modules", ".git", ".venv", "__pycache__", "dist", "build"]):
            continue
        for file in files:
            if file.endswith((".py", ".ts", ".tsx", ".cmd", ".ps1")):
                file_path = Path(root) / file
                # Skip self and test files that legitimately check for these patterns
                if file_path.name in ["verify_integrity.py", "test_integrity_deep.py"]:
                    continue
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    # Look for things like "C:\\Users\\shilo\\Documents\\GitHub\\" that might be hardcoded and missing here
                    if ("shilo" in content or "Documents\\GitHub" in content):
                        # Explicitly skip known false positives in data/registry files if they were to be checked
                        if file_path.name in ["repo_registry.json", "config.py"]:
                             continue
                        print(f"[ERROR] HARDCODED PATH DETECTED: {file_path}")
                        hardcoded_found = True
                except:
                    pass

    if hardcoded_found:
        print("\n[FAIL] Portability check failed due to hardcoded paths.")
        sys.exit(1)

    print("\n--- Integrity Check Complete ---")

if __name__ == "__main__":
    main()
