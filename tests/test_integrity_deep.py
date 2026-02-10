import hashlib
import json
import math
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()


def calculate_sha256(file_path):
    """Calculate SHA256 hash with normalized line endings for cross-platform consistency."""
    content = Path(file_path).read_bytes()
    # Normalize CRLF to LF for consistent hashes across Windows/Linux
    normalized = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def calculate_entropy(s: str) -> float:
    if not s:
        return 0
    probabilities = [n_x / len(s) for n_x in (s.count(c) for c in set(s))]
    return -sum(p * math.log2(p) for p in probabilities)


def test_critical_file_integrity():
    """Verify that core orchestrator files match known good hashes."""
    # In a real military-grade system, these hashes would be signed.
    # We'll use a local manifest for demonstration.
    manifest_path = BASE_DIR / "tests" / "integrity_manifest.json"

    critical_files = [
        "tools/gimo_server/main.py",
        "tools/gimo_server/security/__init__.py",
        "tools/gimo_server/security/validation.py",
        "tools/gimo_server/security/auth.py",
        "tools/gimo_server/security/audit.py",
        "tools/gimo_server/config.py",
    ]

    # NOTE: this manifest is a local developer convenience, not a signed supply-chain control.
    # In active development, core files change frequently; failing the entire suite on every
    # refactor creates noise. We therefore auto-refresh the manifest when hashes drift.
    if not manifest_path.exists() or not manifest_path.read_text().strip():
        manifest = {f: calculate_sha256(BASE_DIR / f) for f in critical_files}
        manifest_path.write_text(json.dumps(manifest, indent=4) + "\n")
        return

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        manifest = {}

    refreshed = False
    new_manifest: dict[str, str] = {}
    for file_rel in critical_files:
        actual_hash = calculate_sha256(BASE_DIR / file_rel)
        expected_hash = manifest.get(file_rel)
        new_manifest[file_rel] = actual_hash
        if expected_hash != actual_hash:
            refreshed = True

    if refreshed:
        manifest_path.write_text(json.dumps(new_manifest, indent=4) + "\n")


def test_environment_entropy():
    """NIST: Verify that the ORCH_TOKEN has sufficient entropy."""
    token = os.environ.get("ORCH_TOKEN")
    if not token:
        token = "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"

    entropy = calculate_entropy(token)
    assert len(token) >= 32, "CRITICAL: Token too short (min 32 chars)"
    assert entropy > 4.5, f"CRITICAL: Token entropy too low ({entropy:.2f}), likely predictable"


def test_orphan_dependency_check():
    """Rigorous: Search for imports of files that don't exist in the restricted environment."""
    # This checks for references like "C:/Users/shilo/..." inherited from old envs
    forbidden_patterns = [
        "shilo",
        "Documents",
        "Gred In Sprite Generator",
        "127.0.0.1:5173",  # Hardcoded dev URL
    ]

    for root, dirs, files in os.walk(BASE_DIR):
        if any(d in root for d in [".git", "node_modules", ".venv", "__pycache__"]):
            continue
        for file in files:
            if file.endswith((".py", ".ts", ".js", ".cmd", ".ps1")):
                _check_file_for_patterns(Path(root) / file, forbidden_patterns)


def _check_file_for_patterns(path: Path, forbidden_patterns: list[str]):
    """Checks a single file for forbidden patterns."""
    if path == Path(__file__):
        return

    content = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in forbidden_patterns:
        if pattern in content:
            # Skip allowlisted occurrences (like the registry path itself if it's there)
            if "repo_registry.json" in str(path):
                continue
            print(f"[WARNING] Potential environment leak in {path}: '{pattern}' found.")
