from types import SimpleNamespace
from unittest.mock import patch

from tools.gimo_server.security.runtime_guard import RuntimeGuard


def _settings(*, enabled: bool = True, block_debugger: bool = False):
    return SimpleNamespace(
        runtime_guard_enabled=enabled,
        runtime_guard_block_debugger=block_debugger,
    )


def test_runtime_guard_disabled_returns_clean_report():
    report = RuntimeGuard(_settings(enabled=False)).evaluate()
    assert report.debugger_detected is False
    assert report.timing_anomaly is False
    assert report.vm_detected is False
    assert report.blocked is False
    assert report.reasons == []


def test_runtime_guard_detects_debugger_without_blocking_by_default():
    with (
        patch("sys.gettrace", return_value=object()),
        patch.object(RuntimeGuard, "_timing_anomaly", return_value=False),
    ):
        report = RuntimeGuard(_settings(enabled=True, block_debugger=False)).evaluate()
    assert report.debugger_detected is True
    assert report.blocked is False
    assert "debugger_detected" in report.reasons


def test_runtime_guard_blocks_when_debugger_and_block_flag_enabled():
    with (
        patch("sys.gettrace", return_value=object()),
        patch.object(RuntimeGuard, "_timing_anomaly", return_value=False),
    ):
        report = RuntimeGuard(_settings(enabled=True, block_debugger=True)).evaluate()
    assert report.debugger_detected is True
    assert report.blocked is True
    assert "debugger_detected" in report.reasons


def test_runtime_guard_detects_vm_keywords_from_platform_data():
    with (
        patch("platform.platform", return_value="Windows-11-VMware"),
        patch("platform.node", return_value="host"),
        patch("platform.processor", return_value="x86_64"),
        patch.dict("os.environ", {"COMPUTERNAME": "my-machine"}, clear=False),
        patch.object(RuntimeGuard, "_timing_anomaly", return_value=False),
    ):
        report = RuntimeGuard(_settings()).evaluate()

    assert report.vm_detected is True
    assert "vmware" in report.vm_indicators
    assert "vm_detected" in report.reasons


def test_runtime_guard_detects_timing_anomaly():
    with patch.object(RuntimeGuard, "_timing_anomaly", return_value=True):
        report = RuntimeGuard(_settings()).evaluate()

    assert report.timing_anomaly is True
    assert "timing_anomaly" in report.reasons
