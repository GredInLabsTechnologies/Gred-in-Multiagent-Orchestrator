import subprocess
import os
from tools.repo_orchestrator.config import SUBPROCESS_TIMEOUT
from tools.repo_orchestrator.security import audit_log


class SystemService:
    """Service to handle Windows system service operations (sc.exe)."""

    @staticmethod
    def get_status(service_name: str = "GILOrchestrator") -> str:
        """Query the state of a Windows service and return a canonical status."""
        try:
            # Headless mode: never touch the OS
            if os.environ.get("ORCH_HEADLESS") == "true":
                return "RUNNING"

            process = subprocess.Popen(
                ["sc", "query", service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout, _ = process.communicate(timeout=SUBPROCESS_TIMEOUT)

            if process.returncode != 0:
                return "STOPPED"

            status_map = {
                "1  STOPPED": "STOPPED",
                "2  START_PENDING": "STARTING",
                "3  STOP_PENDING": "STOPPING",
                "4  RUNNING": "RUNNING",
                "5  CONTINUE_PENDING": "STARTING",
                "6  PAUSE_PENDING": "STOPPING",
                "7  PAUSED": "STOPPED",
            }

            for line in stdout.splitlines():
                if "STATE" in line:
                    raw_val = line.split(":", 1)[-1].strip()
                    for key, val in status_map.items():
                        if key in raw_val:
                            return val
                    return "UNKNOWN"

        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return "UNKNOWN"

        except Exception as e:
            audit_log("SYSTEM", f"STATUS_CHECK_FAILED_{service_name}", str(e))
            return "UNKNOWN"

        return "UNKNOWN"

    @staticmethod
    def restart(service_name: str = "GILOrchestrator", actor: str = "system") -> bool:
        """Restart a Windows service."""
        if os.environ.get("ORCH_HEADLESS") == "true":
            audit_log(
                "SYSTEM",
                f"RESTART_SERVICE_{service_name}",
                "SKIPPED_HEADLESS",
                actor=actor,
            )
            return True

        audit_log(
            "SYSTEM",
            f"RESTART_SERVICE_{service_name}",
            "STARTING",
            actor=actor,
        )

        try:
            subprocess.run(
                ["sc", "stop", service_name],
                timeout=SUBPROCESS_TIMEOUT,
                check=False,
            )
            subprocess.run(
                ["sc", "start", service_name],
                timeout=SUBPROCESS_TIMEOUT,
                check=True,
            )
            audit_log(
                "SYSTEM",
                f"RESTART_SERVICE_{service_name}",
                "SUCCESS",
                actor=actor,
            )
            return True

        except Exception as e:
            audit_log(
                "SYSTEM",
                f"RESTART_SERVICE_FAILED_{service_name}",
                str(e),
                actor=actor,
            )
            return False

    @staticmethod
    def stop(service_name: str = "GILOrchestrator", actor: str = "system") -> bool:
        """Stop a Windows service."""
        if os.environ.get("ORCH_HEADLESS") == "true":
            audit_log(
                "SYSTEM",
                f"STOP_SERVICE_{service_name}",
                "SKIPPED_HEADLESS",
                actor=actor,
            )
            return True

        audit_log(
            "SYSTEM",
            f"STOP_SERVICE_{service_name}",
            "STARTING",
            actor=actor,
        )

        try:
            subprocess.run(
                ["sc", "stop", service_name],
                timeout=SUBPROCESS_TIMEOUT,
                check=True,
            )
            audit_log(
                "SYSTEM",
                f"STOP_SERVICE_{service_name}",
                "SUCCESS",
                actor=actor,
            )
            return True

        except Exception as e:
            audit_log(
                "SYSTEM",
                f"STOP_SERVICE_FAILED_{service_name}",
                str(e),
                actor=actor,
            )
            return False

