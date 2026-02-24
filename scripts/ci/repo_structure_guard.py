"""
GIMO Repo Structure Guard
Enforces structural invariants established by the 2026-02-23 masterplan refactor.
Run this in CI and pre-commit to prevent agents from breaking the clean structure.

Exit code 0 = all checks pass
Exit code 1 = at least one check failed
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent.resolve()

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def check_tools_directory():
    """tools/ must contain ONLY gimo_server/ and orchestrator_ui/."""
    print("\n1. Tools Directory Structure")
    tools = BASE_DIR / "tools"
    allowed = {"gimo_server", "orchestrator_ui", "__pycache__"}
    actual = {d.name for d in tools.iterdir() if d.is_dir()}
    extra = actual - allowed
    check("tools/ has no extra directories", len(extra) == 0,
          f"found: {extra}" if extra else "")


def check_tests_directory():
    """tests/ must follow unit/ + integration/ structure."""
    print("\n2. Tests Directory Structure")
    tests = BASE_DIR / "tests"
    allowed_dirs = {"unit", "integration", "fixtures", "__pycache__"}
    allowed_root_files = {
        "conftest.py", "integrity_manifest.json", "test_mcp_server.py",
        "__init__.py",
    }

    actual_dirs = {d.name for d in tests.iterdir() if d.is_dir()}
    extra_dirs = actual_dirs - allowed_dirs
    check("tests/ has no stray subdirectories", len(extra_dirs) == 0,
          f"found: {extra_dirs}" if extra_dirs else "")

    root_files = {f.name for f in tests.iterdir() if f.is_file()}
    extra_files = root_files - allowed_root_files
    check("tests/ has no stray root files", len(extra_files) == 0,
          f"found: {extra_files}" if extra_files else "")

    # No legacy naming patterns
    for test_file in tests.rglob("test_*.py"):
        name = test_file.stem
        for bad in ("_v2", "_remaining", "_hardened"):
            check(f"{test_file.name} has no '{bad}' suffix",
                  bad not in name, str(test_file.relative_to(BASE_DIR)))


def check_scripts_count():
    """scripts/ must have ≤15 files."""
    print("\n3. Scripts Count")
    scripts = BASE_DIR / "scripts"
    all_files = list(scripts.rglob("*"))
    actual_files = [f for f in all_files if f.is_file() and f.name != "__init__.py"]
    check(f"scripts/ has <=15 files (found {len(actual_files)})",
          len(actual_files) <= 15)


def check_docs_count():
    """docs/ root must have ≤10 .md files."""
    print("\n4. Documentation Count")
    docs = BASE_DIR / "docs"
    md_files = list(docs.glob("*.md"))
    check(f"docs/ root has <=10 .md files (found {len(md_files)})",
          len(md_files) <= 10)


def check_root_cleanliness():
    """Root must not have stray scripts, logs, or debug files."""
    print("\n5. Root Cleanliness")
    allowed_root = {
        # Standard project files
        "README.md", ".gitignore", ".pre-commit-config.yaml",
        "pyproject.toml", "requirements.txt", "requirements-dev.txt", "LICENSE",
        ".env", ".env.example", "conftest.py",
        # MCP / Claude config
        ".mcp.json",
    }
    stray_extensions = {".py", ".cmd", ".bat", ".ps1", ".log", ".txt"}

    stray = []
    for f in BASE_DIR.iterdir():
        if f.is_dir():
            continue
        if f.name.startswith("."):
            continue
        if f.name in allowed_root:
            continue
        if f.suffix in stray_extensions:
            stray.append(f.name)

    check("root has no stray scripts/logs", len(stray) == 0,
          f"found: {stray}" if stray else "")


def check_dead_imports():
    """No imports to deleted legacy modules."""
    print("\n6. Dead Import Check")
    dead_modules = [
        "from tools.gptactions_gateway",
        "from tools.patch_validator",
        "from tools.patch_integrator",
        "from tools.gimo_mcp",
        "from tools.repo_orchestrator",
        "from tools.llm_security",
    ]

    violations = []
    for py_file in BASE_DIR.rglob("*.py"):
        if any(d in str(py_file) for d in [".git", "node_modules", ".venv", "__pycache__", "tmp"]):
            continue
        if py_file.name == "repo_structure_guard.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for mod in dead_modules:
                if mod in content:
                    violations.append(f"{py_file.relative_to(BASE_DIR)}: {mod}")
        except Exception:
            pass

    check("zero imports to deleted modules", len(violations) == 0,
          "; ".join(violations[:5]) if violations else "")


def check_pycache_not_tracked():
    """No __pycache__ should be tracked in git."""
    print("\n7. Git Hygiene")
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=10
        )
        tracked = [f for f in result.stdout.splitlines() if "__pycache__" in f]
        check("no __pycache__ tracked in git", len(tracked) == 0,
              f"found {len(tracked)} tracked" if tracked else "")
    except Exception:
        check("no __pycache__ tracked in git (git unavailable)", True)


def main():
    print("=" * 55)
    print(" GIMO REPO STRUCTURE GUARD")
    print("=" * 55)

    check_tools_directory()
    check_tests_directory()
    check_scripts_count()
    check_docs_count()
    check_root_cleanliness()
    check_dead_imports()
    check_pycache_not_tracked()

    print(f"\n{'=' * 55}")
    print(f" RESULT: {PASS} passed, {FAIL} failed")
    print(f"{'=' * 55}")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
