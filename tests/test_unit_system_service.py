import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.gimo_server.services.system_service import SystemService


class TestSystemService(unittest.TestCase):

    def setUp(self):
        # Clear environment variable before each test
        self.old_headless = os.environ.get("ORCH_HEADLESS")
        if "ORCH_HEADLESS" in os.environ:
            del os.environ["ORCH_HEADLESS"]

    def tearDown(self):
        # Restore environment variable
        if self.old_headless is not None:
            os.environ["ORCH_HEADLESS"] = self.old_headless
        elif "ORCH_HEADLESS" in os.environ:
            del os.environ["ORCH_HEADLESS"]

    @patch("tools.gimo_server.services.system_service.subprocess.Popen")
    def test_get_status_running(self, mock_popen):
        # Mock successful sc query output
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("STATE : 4 RUNNING", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        status = SystemService.get_status("TestService")
        self.assertEqual(status, "4 RUNNING")

    @patch("tools.gimo_server.services.system_service.subprocess.Popen")
    def test_get_status_headless(self, mock_popen):
        os.environ["ORCH_HEADLESS"] = "true"
        status = SystemService.get_status("TestService")
        self.assertEqual(status, "RUNNING (MOCK)")
        mock_popen.assert_not_called()

    @patch("tools.gimo_server.services.system_service.subprocess.run")
    def test_stop_service_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        success = SystemService.stop("TestService", actor="tester")
        self.assertTrue(success)
        mock_run.assert_called()

    @patch("tools.gimo_server.services.system_service.subprocess.run")
    def test_restart_service_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        success = SystemService.restart("TestService", actor="tester")
        self.assertTrue(success)
        # Should call stop then start
        self.assertGreaterEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
