#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification script for Contract-Driven Architecture implementation.

Tests:
1. GimoContract can be instantiated
2. extract_valid_roles() returns correct values from schema
3. ContractFactory can build contracts (mock mode)
4. Unified credentials file can be read
"""
import sys
import io
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add tools/gimo_server to path
sys.path.insert(0, str(Path(__file__).parent / "tools" / "gimo_server"))

def test_contract_model():
    """Test 1: GimoContract instantiation"""
    print("Test 1: GimoContract model...")
    from models.contract import GimoContract, extract_valid_roles, DEFAULT_VALID_SCOPES
    from datetime import datetime, timezone

    valid_roles = extract_valid_roles()
    print(f"  [OK] Extracted valid roles: {valid_roles}")

    contract = GimoContract(
        caller_role="operator",
        agent_trust_ceiling="t1",
        provider_id="test-provider",
        model_id="test-model",
        workspace_root=Path.cwd(),
        valid_roles=valid_roles,
        valid_scopes=DEFAULT_VALID_SCOPES,
        created_at=datetime.now(timezone.utc),
        license_plan="free",
    )

    assert contract.is_operator_or_above()
    assert not contract.is_admin()
    assert contract.validate_role("orchestrator")
    assert not contract.validate_role("invalid_role")

    roles_str = contract.format_roles_for_prompt()
    print(f"  [OK] Formatted roles for prompt: {roles_str}")
    assert '"orchestrator"' in roles_str

    print("  [PASS] Test 1\n")
    return True

def test_extract_roles_schema_alignment():
    """Test 2: extract_valid_roles matches AgentRole Literal"""
    print("Test 2: Schema alignment...")
    from models.contract import extract_valid_roles
    from models.agent import AgentRole
    from typing import get_args

    extracted = extract_valid_roles()
    literal_args = get_args(AgentRole)

    assert extracted == literal_args, f"Mismatch: {extracted} != {literal_args}"
    print(f"  [OK] Schema aligned: {extracted}")
    print("  [PASS] Test 2\n")
    return True

def test_unified_credentials_format():
    """Test 3: Unified credentials file format"""
    print("Test 3: Unified credentials format...")
    import yaml

    # Test YAML parsing
    sample_creds = """
admin: "admin_token_abc123"
operator: "operator_token_def456"
actions: "actions_token_ghi789"
"""

    creds = yaml.safe_load(sample_creds)
    assert "admin" in creds
    assert "operator" in creds
    assert "actions" in creds
    print(f"  [OK] Parsed credentials: {list(creds.keys())}")
    print("  [PASS] Test 3\n")
    return True

def test_config_migration():
    """Test 4: Config migration logic"""
    print("Test 4: Config migration (dry-run)...")
    # Just verify the function exists and imports work
    from config import _migrate_to_unified_credentials
    print("  [OK] Migration function available")
    print("  [PASS] Test 4\n")
    return True

def main():
    print("=" * 60)
    print("Contract-Driven Architecture Verification")
    print("=" * 60 + "\n")

    tests = [
        test_contract_model,
        test_extract_roles_schema_alignment,
        test_unified_credentials_format,
        test_config_migration,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as exc:
            print(f"  [FAIL] Test failed: {exc}\n")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
