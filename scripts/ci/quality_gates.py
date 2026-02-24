import os
import subprocess
import sys
from pathlib import Path

# scripts/ci/*.py -> repo root
BASE_DIR = Path(__file__).parent.parent.parent.resolve()


def run_step(name, command):
    print(f"\n>>> Running {name}...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE_DIR)
    try:
        # Split command into list to avoid shell=True security risk
        import shlex

        cmd_list = shlex.split(command)
        # Ensure pytest is executed in the current interpreter environment.
        if cmd_list and cmd_list[0] == "pytest":
            cmd_list = [sys.executable, "-m", "pytest", *cmd_list[1:]]
        process = subprocess.Popen(
            cmd_list,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            env=env,
        )
        for line in process.stdout:
            print(f"  {line.strip()}")
        process.wait()
        if process.returncode == 0:
            print(f"[PASSED] {name}")
            return True
        else:
            print(f"[FAILED] {name} (Exit code: {process.returncode})")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to run {name}: {e}")
        return False


def main():
    print("=" * 60)
    print(" GRED-REPO-ORCHESTRATOR ULTIMATE QUALITY GATES")
    print("=" * 60)

    # 0. Repo structure guard: enforce post-refactor invariants
    gate0 = run_step(
        "Repo Structure Guard",
        "python scripts/ci/repo_structure_guard.py",
    )

    # 1. Repo policy: do not track generated artifacts
    gate1 = run_step(
        "Repo Policy (no generated artifacts tracked)",
        "python scripts/ci/check_no_artifacts.py --tracked",
    )

    # 2. Security guards suite
    gate2 = run_step(
        "Security Guards Suite",
        "pytest tests/unit/test_security_guards.py -v",
    )

    # 3. Deep integrity audit
    gate3 = run_step(
        "Deep Integrity Audit",
        "pytest tests/integration/test_integrity.py -v",
    )

    # 4. Diagnostic integrity
    gate4 = run_step("Diagnostic Script", "python scripts/ci/verify_integrity.py")

    print("\n" + "=" * 60)
    if all([gate0, gate1, gate2, gate3, gate4]):
        print(" FINAL RESULT: ALL GATES PASSED [SECURITY CERTIFIED]")
        print("=" * 60)
        sys.exit(0)
    else:
        print(" FINAL RESULT: GATES FAILED [SYSTEM COMPROMISED OR DEGRADED]")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
