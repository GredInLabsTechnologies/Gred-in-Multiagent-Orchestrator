from __future__ import annotations

import json

from tools.gimo_server.services.runtime_policy_service import RuntimePolicyService


def test_runtime_policy_allow_flow(monkeypatch, tmp_path):
    policy_path = tmp_path / "state" / "policy.json"
    baseline_path = tmp_path / "runtime" / "baseline_manifest.json"
    monkeypatch.setattr(RuntimePolicyService, "POLICY_PATH", policy_path)
    monkeypatch.setattr(RuntimePolicyService, "BASELINE_PATH", baseline_path)

    RuntimePolicyService.ensure_runtime_files()
    decision = RuntimePolicyService.evaluate_draft_policy(
        path_scope=["tools/gimo_server/services/runtime_policy_service.py"],
        estimated_files_changed=1,
        estimated_loc_changed=20,
    )
    assert decision.decision == "allow"
    assert decision.status_code == "POLICY_ALLOW"
    assert decision.policy_hash_expected == decision.policy_hash_runtime


def test_runtime_policy_detects_tamper(monkeypatch, tmp_path):
    policy_path = tmp_path / "state" / "policy.json"
    baseline_path = tmp_path / "runtime" / "baseline_manifest.json"
    monkeypatch.setattr(RuntimePolicyService, "POLICY_PATH", policy_path)
    monkeypatch.setattr(RuntimePolicyService, "BASELINE_PATH", baseline_path)

    RuntimePolicyService.ensure_runtime_files()
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    payload["forbidden_paths"] = ["secrets"]
    policy_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    decision = RuntimePolicyService.evaluate_draft_policy(path_scope=["src/main.py"])
    assert decision.decision == "deny"
    assert decision.status_code == "BASELINE_TAMPER_DETECTED"


def test_runtime_policy_forbidden_scope(monkeypatch, tmp_path):
    policy_path = tmp_path / "state" / "policy.json"
    baseline_path = tmp_path / "runtime" / "baseline_manifest.json"
    monkeypatch.setattr(RuntimePolicyService, "POLICY_PATH", policy_path)
    monkeypatch.setattr(RuntimePolicyService, "BASELINE_PATH", baseline_path)

    RuntimePolicyService.ensure_runtime_files()
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    payload["forbidden_paths"] = ["tools/gimo_server/security"]
    policy_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    policy = RuntimePolicyService.load_policy_config()
    expected_hash = RuntimePolicyService.compute_policy_hash(policy)
    baseline_path.write_text(
        json.dumps(
            {
                "baseline_version": "v1",
                "policy_schema_version": "1.0",
                "policy_hash_expected": expected_hash,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    decision = RuntimePolicyService.evaluate_draft_policy(
        path_scope=["tools/gimo_server/security/auth.py"],
        estimated_files_changed=1,
        estimated_loc_changed=12,
    )
    assert decision.decision == "deny"
    assert decision.status_code == "DRAFT_REJECTED_FORBIDDEN_SCOPE"
    assert any("forbidden_path" in rule for rule in decision.triggered_rules)


def test_runtime_policy_estimate_change_scope_uses_complexity_defaults():
    files_changed, loc_changed = RuntimePolicyService.estimate_change_scope(
        path_scope=["src/main.py", "src/util.py"],
        complexity_band="high",
    )

    assert files_changed == 2
    assert loc_changed == 640
