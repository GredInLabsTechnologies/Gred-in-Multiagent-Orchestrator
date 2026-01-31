import subprocess
import sys

# Run specific failing tests one by one
tests = [
    "tests/test_api_open_repo.py::test_api_open_repo_decoupled",
    "tests/test_api_td002.py::test_api_vitaminize_success",
    "tests/test_integrity_deep.py::test_critical_file_integrity",
    "tests/test_security_hardened.py::test_auth_rejection_triggers_panic",
]

for test in tests:
    print(f"\n{'='*60}")
    print(f"Running: {test}")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test, "-xvs", "--tb=short"], capture_output=True, text=True
    )

    # Print last 30 lines of output
    output_lines = result.stdout.split("\n") + result.stderr.split("\n")
    relevant_lines = [l for l in output_lines if l.strip()]
    for line in relevant_lines[-30:]:
        print(line)
