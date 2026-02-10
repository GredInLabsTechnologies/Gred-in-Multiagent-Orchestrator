"""
Gred-Repo-Orchestrator Integrity Check Script
Refactored to reduce cognitive complexity (S3776)
"""

import json
import os
import sys
from pathlib import Path


def check_json_file(path: Path, required_keys: list[str] | None = None) -> dict | None:
    """Validate a JSON file exists and contains required keys."""
    if not path.exists():
        print(f"[ERROR] Missing file: {path}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if required_keys:
                for key in required_keys:
                    if key not in data:
                        print(f"[ERROR] Missing key '{key}' in {path}")
            return data
    except Exception as e:
        print(f"[ERROR] Failed to parse {path}: {e}")
        return None


def validate_config_files(base_dir: Path) -> dict | None:
    """Validate JSON configuration files."""
    print("\n1. Validating JSON Configuration Files:")
    repo_registry = check_json_file(
        base_dir / "tools" / "gimo_server" / "repo_registry.json", ["repos", "active_repo"]
    )
    check_json_file(base_dir / "tools" / "gimo_server" / "allowed_paths.json", ["paths"])
    check_json_file(
        base_dir / "tools" / "gimo_server" / "security_db.json",
        ["panic_mode", "blacklist", "recent_events"],
    )
    return repo_registry


def verify_repo_paths(repo_registry: dict) -> None:
    """Verify that registered repository paths exist."""
    print("\n2. Verifying Repository Paths:")
    for repo_path in repo_registry.get("repos", []):
        if os.path.exists(repo_path):
            print(f"[OK] {repo_path}")
        else:
            print(f"[WARNING] Missing Repository: {repo_path}")


def check_environment_variables() -> None:
    """Check for required environment variables."""
    print("\n3. Environment Variables (Required in OS or .env):")
    required_envs = ["ORCH_TOKEN", "ORCH_REPO_ROOT"]
    for env in required_envs:
        if os.environ.get(env):
            print(f"[OK] {env} is set")
        else:
            print(f"[INFO] {env} is not set in current shell (check your .env)")


def is_excluded_directory(root: str) -> bool:
    """Check if directory should be excluded from scan."""
    excluded = ["node_modules", ".git", ".venv", "__pycache__", "dist", "build"]
    return any(d in root for d in excluded)


def should_skip_file(file_path: Path) -> bool:
    """Check if file should be skipped from hardcoded path detection."""
    skip_files = [
        "verify_integrity.py",
        "test_integrity_deep.py",
        "repo_registry.json",
        "config.py",
    ]
    return file_path.name in skip_files


def is_code_file(filename: str) -> bool:
    """Check if file is a code file that should be scanned."""
    return filename.endswith((".py", ".ts", ".tsx", ".cmd", ".ps1"))


def has_hardcoded_paths(file_path: Path) -> bool:
    """Check if a file contains hardcoded paths."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        return "shilo" in content or "Documents\\GitHub" in content
    except Exception:
        return False


def scan_directory_for_hardcoded_paths(base_dir: Path) -> list[Path]:
    """Scan directory tree for files with hardcoded paths."""
    flagged_files: list[Path] = []

    for root, _dirs, files in os.walk(base_dir):
        if is_excluded_directory(root):
            continue

        for filename in files:
            if not is_code_file(filename):
                continue

            file_path = Path(root) / filename
            if should_skip_file(file_path):
                continue

            if has_hardcoded_paths(file_path):
                flagged_files.append(file_path)

    return flagged_files


def check_hardcoded_paths(base_dir: Path) -> bool:
    """Search for hardcoded paths in code files."""
    print("\n4. Migration Check (Searching for missing file references):")

    flagged_files = scan_directory_for_hardcoded_paths(base_dir)

    for file_path in flagged_files:
        print(f"[ERROR] HARDCODED PATH DETECTED: {file_path}")

    return len(flagged_files) > 0


def main():
    """Main entry point for integrity check."""
    print("--- Gred-Repo-Orchestrator Integrity Check ---")
    # scripts/ci/*.py -> repo root
    base_dir = Path(__file__).parent.parent.parent.resolve()
    print(f"Base Directory: {base_dir}")

    # 1. Config Files
    repo_registry = validate_config_files(base_dir)

    # 2. Repo Existence
    if repo_registry:
        verify_repo_paths(repo_registry)

    # 3. Environment Variables
    check_environment_variables()

    # 4. Migration Check
    hardcoded_found = check_hardcoded_paths(base_dir)

    if hardcoded_found:
        print("\n[FAIL] Portability check failed due to hardcoded paths.")
        sys.exit(1)

    print("\n--- Integrity Check Complete ---")


if __name__ == "__main__":
    main()
