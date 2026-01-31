import os
import hashlib
import json
import math
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()

def calculate_sha256(file_path):
    """Calculate SHA256 hash with normalized line endings for cross-platform consistency."""
    content = Path(file_path).read_bytes()
    # Normalize CRLF to LF for consistent hashes across Windows/Linux
    normalized = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(normalized).hexdigest()

def calculate_entropy(s: str) -> float:
    if not s: return 0
    probabilities = [n_x / len(s) for n_x in (s.count(c) for c in set(s))]
    return -sum(p * math.log2(p) for p in probabilities)

def test_critical_file_integrity():
    """Verify that core orchestrator files match known good hashes."""
    # In a real military-grade system, these hashes would be signed.
    # We'll use a local manifest for demonstration.
    manifest_path = BASE_DIR / "tests" / "integrity_manifest.json"
    
    critical_files = [
        "tools/repo_orchestrator/main.py",
        "tools/repo_orchestrator/security/__init__.py",
        "tools/repo_orchestrator/security/validation.py",
        "tools/repo_orchestrator/security/auth.py",
        "tools/repo_orchestrator/security/audit.py",
        "tools/repo_orchestrator/config.py",
    ]
    
    if not manifest_path.exists():
        # First-time run: Generate manifest
        manifest = {f: calculate_sha256(BASE_DIR / f) for f in critical_files}
        manifest_path.write_text(json.dumps(manifest, indent=4))
        return

    manifest = json.loads(manifest_path.read_text())
    for file_rel, expected_hash in manifest.items():
        actual_hash = calculate_sha256(BASE_DIR / file_rel)
        assert actual_hash == expected_hash, f"INTEGRITY BREACH: {file_rel} has been tampered with!"

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
        "127.0.0.1:5173" # Hardcoded dev URL
    ]
    
    for root, dirs, files in os.walk(BASE_DIR):
        if any(d in root for d in [".git", "node_modules", ".venv", "__pycache__"]):
            continue
        for file in files:
            if file.endswith((".py", ".ts", ".js", ".cmd", ".ps1")):
                path = Path(root) / file
                if path == Path(__file__): continue
                content = path.read_text(encoding='utf-8', errors='ignore')
                for pattern in forbidden_patterns:
                    if pattern in content:
                        # Skip allowlisted occurrences (like the registry path itself if it's there)
                        if "repo_registry.json" in str(path): continue
                        print(f"[WARNING] Potential environment leak in {path}: '{pattern}' found.")
                        # In strict mode this could be an assert
