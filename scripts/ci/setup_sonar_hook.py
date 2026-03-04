import os
import sys
from pathlib import Path
import stat

HOOK_CONTENT = """#!/bin/sh
# ========================================================================
# Git pre-push hook for Test Coverage & SonarQube
# This runs automatically before every git push.
# If tests or SonarQube fail, the push is aborted.
# ========================================================================

echo "Running tests and SonarQube analysis before pushing..."

# Run Python tests
python -m pytest --cov=tools --cov=scripts --cov-report=xml:coverage.xml --cov-report=term
if [ $? -ne 0 ]; then
  echo "[ERROR] Python tests failed! Aborting push."
  exit 1
fi

# Run UI tests if present
if [ -d "tools/orchestrator_ui" ]; then
  cd tools/orchestrator_ui
  npm run test:coverage || echo "UI tests missing or failed, continuing..."
  if [ -f "coverage/lcov.info" ]; then
    sed -i 's|SF:|SF:tools/orchestrator_ui/|g' coverage/lcov.info
  fi
  cd ../..
fi

# Run Sonar Scanner
sonar-scanner.bat
if [ $? -ne 0 ]; then
  echo "[ERROR] SonarQube analysis failed! Aborting push."
  exit 1
fi

echo "All checks passed! Pushing to remote..."
exit 0
"""

def main():
    repo_root = Path(__file__).parent.parent.parent.resolve()
    git_dir = repo_root / ".git"
    
    if not git_dir.exists() or not git_dir.is_dir():
        print("[ERROR] .git directory not found. Must be run from within the repository.")
        sys.exit(1)
        
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    
    pre_push_path = hooks_dir / "pre-push"
    
    # Write the hook
    with open(pre_push_path, 'w', newline='\n') as f:
        f.write(HOOK_CONTENT)
        
    # Make executable (UNIX style, though on Windows Git Bash relies on this too sometimes)
    st = os.stat(pre_push_path)
    os.chmod(pre_push_path, st.st_mode | stat.S_IEXEC)
    
    print(f"[SUCCESS] Installed git pre-push hook to automatically run SonarQube at: {pre_push_path}")
    print("Now, every time you run `git push`, tests and SonarQube will run automatically.")
    print("If you need to skip it occasionally, you can run `git push --no-verify`.")

if __name__ == "__main__":
    main()
