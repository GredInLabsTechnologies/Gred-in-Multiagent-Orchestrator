import json

from tools.llm_security.audit import LLMAuditLogger


def test_audit_logger_creation(tmp_path):
    log_file = tmp_path / "audit.log"
    _logger = LLMAuditLogger(log_file)  # noqa: F841
    assert log_file.exists()


def test_log_interaction(tmp_path):
    log_file = tmp_path / "audit.log"
    logger = LLMAuditLogger(log_file)

    interaction_id = "test-id-123"
    phase = "input_sanitization"
    data = {"input_length": 100, "detected_secrets": ["api_key"]}
    action = "ALLOW"
    reason = "Test reason"

    logger.log_interaction(interaction_id, phase, data, action, reason)

    content = log_file.read_text()
    assert interaction_id in content
    log_json_str = content.split(" | INFO | ")[1]
    log_data = json.loads(log_json_str)
    assert log_data["interaction_id"] == interaction_id
    assert log_data["phase"] == phase
    assert log_data["action"] == action
    assert "timestamp" in log_data


def test_log_alert(tmp_path):
    log_file = tmp_path / "audit.log"
    logger = LLMAuditLogger(log_file)

    severity = "CRITICAL"
    message = "Potential intrusion"
    details = {"ip": "1.2.3.4"}

    logger.log_alert(severity, message, details)

    content = log_file.read_text()
    assert "WARNING" in content
    log_json_str = content.split(" | WARNING | ")[1]
    log_data = json.loads(log_json_str)
    assert log_data["type"] == "SECURITY_ALERT"
    assert log_data["severity"] == severity


def test_append_only_logging(tmp_path):
    log_file = tmp_path / "audit.log"
    logger = LLMAuditLogger(log_file)

    logger.log_interaction("id1", "phase1", {}, "ALLOW", "reason1")
    logger.log_interaction("id2", "phase2", {}, "DENY", "reason2")

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert "id1" in lines[0]
    assert "id2" in lines[1]
