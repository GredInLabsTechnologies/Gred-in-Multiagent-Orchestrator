import os
import subprocess

from tools.gimo_server.config import SUBPROCESS_TIMEOUT
from tools.gimo_server.security import audit_log


class SystemService:
    """Service to handle Windows system service operations (sc.exe)."""

    _STATUS_BY_SC_CODE = {
        "1": "STOPPED",
        "2": "STARTING",
        "3": "STOPPING",
        "4": "RUNNING",
        "5": "STARTING",
        "6": "STOPPING",
        "7": "STOPPED",
    }
    _STATUS_BY_TOKEN = {
        "RUNNING": "RUNNING",
        "START_PENDING": "STARTING",
        "CONTINUE_PENDING": "STARTING",
        "STARTING": "STARTING",
        "STOP_PENDING": "STOPPING",
        "PAUSE_PENDING": "STOPPING",
        "STOPPING": "STOPPING",
        "STOPPED": "STOPPED",
        "PAUSED": "STOPPED",
    }

    @classmethod
    def normalize_status(cls, raw_status: str | None) -> str:
        """Collapse OS-specific service states into the UI's canonical enum set."""
        value = str(raw_status or "").strip().upper()
        if not value:
            return "UNKNOWN"

        tokens = (
            value.replace("(", " ")
            .replace(")", " ")
            .replace(":", " ")
            .split()
        )

        for token in tokens:
            mapped = cls._STATUS_BY_SC_CODE.get(token)
            if mapped:
                return mapped

        for token in tokens:
            mapped = cls._STATUS_BY_TOKEN.get(token)
            if mapped:
                return mapped

        return "UNKNOWN"

    @staticmethod
    def get_status(service_name: str = "GIMO") -> str:
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

            for line in stdout.splitlines():
                if "STATE" in line:
                    raw_val = line.split(":", 1)[-1].strip()
                    return SystemService.normalize_status(raw_val)

        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return "UNKNOWN"

        except Exception as e:
            audit_log("SYSTEM", f"STATUS_CHECK_FAILED_{service_name}", str(e))
            return "UNKNOWN"

        return "UNKNOWN"

    @staticmethod
    def restart(service_name: str = "GIMO", actor: str = "system") -> bool:
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
    def stop(service_name: str = "GIMO", actor: str = "system") -> bool:
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
