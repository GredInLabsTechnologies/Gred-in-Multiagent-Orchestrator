import os
import subprocess
from unittest.mock import MagicMock, patch

from tools.gimo_server.services.system_service import SystemService


def test_get_status_headless():
    with patch.dict(os.environ, {"ORCH_HEADLESS": "true"}):
        assert SystemService.get_status() == "RUNNING (MOCK)"


def test_get_status_running():
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("STATE: 4 RUNNING", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        assert SystemService.get_status() == "4 RUNNING"


def test_get_status_stopped():
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "error")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        assert SystemService.get_status() == "STOPPED"


def test_get_status_timeout():
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        # Raise on first call, return value on second
        mock_process.communicate.side_effect = [
            subprocess.TimeoutExpired(["sc"], timeout=10),
            ("", ""),
        ]
        mock_popen.return_value = mock_process

        assert SystemService.get_status() == "UNKNOWN"
        mock_process.kill.assert_called_once()


def test_get_status_exception():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = Exception("error")
        assert SystemService.get_status() == "UNKNOWN"


def test_get_status_no_state():
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("garbled output", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        assert SystemService.get_status() == "UNKNOWN"


def test_restart_headless():
    with patch.dict(os.environ, {"ORCH_HEADLESS": "true"}):
        assert SystemService.restart() == True


def test_restart_success():
    with patch("subprocess.run") as mock_run:
        assert SystemService.restart() == True
        assert mock_run.call_count == 2


def test_restart_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("fail")
        assert SystemService.restart() == False


def test_stop_headless():
    with patch.dict(os.environ, {"ORCH_HEADLESS": "true"}):
        assert SystemService.stop() == True


def test_stop_success():
    with patch("subprocess.run") as mock_run:
        assert SystemService.stop() == True
        mock_run.assert_called_once()


def test_stop_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("fail")
        assert SystemService.stop() == False
