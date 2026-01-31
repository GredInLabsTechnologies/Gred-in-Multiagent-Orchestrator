import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()


def run_step(name, command):
    print(f"\n>>> Running {name}...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE_DIR)
    try:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
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

    # 1. Functional & Security Tests
    gate1 = run_step("Hardened Security Suite", "pytest tests/test_security_hardened.py -v")

    # 2. Deep Integrity Audit
    gate2 = run_step("Deep Integrity Audit", "pytest tests/test_integrity_deep.py -v")

    # 3. API Fuzzing (Rigorous)
    gate3 = run_step("API Fuzzing Pass", "pytest tests/test_fuzzing.py -v")

    # 4. Diagnostic Integrity
    gate4 = run_step("Diagnostic Script", "python scripts/verify_integrity.py")

    print("\n" + "=" * 60)
    if all([gate1, gate2, gate3, gate4]):
        print(" FINAL RESULT: ALL GATES PASSED [SECURITY CERTIFIED]")
        print("=" * 60)
        sys.exit(0)
    else:
        print(" FINAL RESULT: GATES FAILED [SYSTEM COMPROMISED OR DEGRADED]")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
