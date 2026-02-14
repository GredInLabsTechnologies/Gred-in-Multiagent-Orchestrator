import time
import pytest
from tools.gimo_server.security.threat_level import ThreatEngine, ThreatLevel, EventSeverity

def test_threat_engine_initial_state():
    engine = ThreatEngine()
    assert engine.level == ThreatLevel.NOMINAL
    assert engine.level_label == "NOMINAL"
    assert engine.decay_remaining_seconds() is None

def test_threat_engine_escalation_low_threshold():
    engine = ThreatEngine()
    # 3 failures from same source -> ALERT
    for _ in range(3):
        engine.record_auth_failure("1.2.3.4")
    
    assert engine.level == ThreatLevel.ALERT
    assert engine.level_label == "ALERT"

def test_threat_engine_escalation_guarded():
    engine = ThreatEngine()
    # 5 failures total -> GUARDED
    for i in range(5):
        engine.record_auth_failure(f"1.2.3.{i}")
    
    assert engine.level == ThreatLevel.GUARDED
    assert engine.level_label == "GUARDED"

def test_threat_engine_escalation_lockdown():
    engine = ThreatEngine()
    # 10 failures total -> LOCKDOWN
    for i in range(10):
        engine.record_auth_failure(f"1.2.3.{i}")
    
    assert engine.level == ThreatLevel.LOCKDOWN
    assert engine.level_label == "LOCKDOWN"

def test_threat_engine_whitelist():
    engine = ThreatEngine()
    # Whitelisted sources don't escalate
    for _ in range(20):
        engine.record_auth_failure("127.0.0.1")
    
    assert engine.level == ThreatLevel.NOMINAL

def test_threat_engine_per_source_tracking():
    engine = ThreatEngine()
    # 2 failures from source A -> NOMINAL (threshold is 3 per source for ALERT)
    for _ in range(2):
        engine.record_auth_failure("A")
    
    assert engine.level == ThreatLevel.NOMINAL
    
    # 1 more from A -> ALERT (Total=3, A=3)
    engine.record_auth_failure("A")
    assert engine.level == ThreatLevel.ALERT

def test_threat_engine_operational_exceptions_ignored():
    engine = ThreatEngine()
    # Connection errors don't escalate
    engine.record_exception("1.2.3.4", ConnectionError("Timeout"))
    assert engine.level == ThreatLevel.NOMINAL
    
    # Security exceptions do escalate
    for _ in range(5):
        engine.record_exception("1.2.3.4", ValueError("Security Probe"))
    assert engine.level == ThreatLevel.GUARDED

def test_threat_engine_manual_actions():
    engine = ThreatEngine()
    for _ in range(10):
        engine.record_auth_failure("1.2.3.4")
    assert engine.level == ThreatLevel.LOCKDOWN
    
    engine.downgrade()
    assert engine.level == ThreatLevel.GUARDED
    
    engine.clear_all()
    assert engine.level == ThreatLevel.NOMINAL

def test_threat_engine_decay(monkeypatch):
    engine = ThreatEngine()
    engine.record_auth_failure("1.2.3.4")
    engine.record_auth_failure("1.2.3.4")
    engine.record_auth_failure("1.2.3.4")
    assert engine.level == ThreatLevel.ALERT
    
    # Mock time to simulated 10 minutes later
    future = time.time() + 600
    monkeypatch.setattr(time, "time", lambda: future)
    
    assert engine.tick_decay() is True
    assert engine.level == ThreatLevel.NOMINAL

def test_threat_engine_snapshot():
    engine = ThreatEngine()
    engine.record_auth_failure("1.2.3.4")
    snapshot = engine.snapshot()
    
    assert snapshot["threat_level"] == 0
    assert snapshot["active_sources"] == 1
    assert "panic_mode" in snapshot
    assert snapshot["threat_level_label"] == "NOMINAL"
    assert snapshot["auto_decay_remaining"] is None

def test_startup_reset():
    """Verify that al arrancar el threat level es NOMINAL."""
    # This is also tested by the engine initialization
    engine = ThreatEngine()
    assert engine.level == ThreatLevel.NOMINAL

def test_backward_compat_panic_mode():
    """Verifica que panic_mode sigue funcionando como alias."""
    engine = ThreatEngine()
    
    # NOMINAL
    assert engine.snapshot()["panic_mode"] is False
    
    # Forces LOCKDOWN
    engine.level = ThreatLevel.LOCKDOWN
    assert engine.snapshot()["panic_mode"] is True
    
    # GUARDED should still be False (panic_mode = LOCKDOWN)
    engine.level = ThreatLevel.GUARDED
    assert engine.snapshot()["panic_mode"] is False
